# pilot_001 — corrected numbers (Phase 0, Tasks 2–5)

- **Scope:** this document establishes which pilot_001 figures may be quoted in the thesis, and with which corrected values. It implements no fixes; the companion fix list lives elsewhere. `thesis/results/` was treated as frozen evidence throughout.
- **Method (2026-08-22):** each task was executed by an independent analysis agent with full re-derivation from primary data (overview.csv, the seven run dirs' stage JSONLs, driver sources), plus Docker execution probes where records alone could not decide (image `pareval-thesis:latest`, repo mounted read-only, all builds in a session scratchpad). Tasks 2, 3 and 5 were then adversarially verified by second agents mandated to refute them: all three verifications returned **CONFIRMED**, with the peripheral corrections noted inline at the end of each section. Task 4 is direct measurement with its command receipts.
- **Headline outcome:** the two design-core figures — 13.8 % "statically clean but ParEval-incorrect" and 16.8 % "statically clean but enhanced-failing" — do not survive. Doubly corrected (oracle-defective benchmarks out, tool-complete subset only) they become **2.7 % (6/225)** and **8.9 % (20/225)** for `static_feedback`, and per-sample classification reduces the genuinely-model-caused residue further to **2.2 %** and **3.6 %**. The phenomenon the thesis design predicts is real — statically clean code with functional bugs exists and the pipeline catches it — but it is a factor ~5 smaller than overview.md states, and the corrected number is now backed by per-sample receipts instead of an aggregate.

---

# Task 2 — Doubly-corrected headline numbers

All numbers below are re-derived from primary data (`thesis/results/analysis/pilot_001/overview.csv`, 1903 rows, and the seven `thesis/results/intermediate/pilot_001*` run dirs). Nothing was quoted from the prior audits. `thesis/results/` was not modified; all executions ran from read-only mounts into the session scratchpad.

## 2.0 Definitions as used (with receipts)

**Clean final** — exactly the population `build_overview.py::clean_but_incorrect` (thesis/analysis_overview/build_overview.py:1062-1103) uses: per `(model, sample_id)` within a variant, the row with the highest iteration must have `status == "stopped_clean"`; the counted artifact is the carry-forward effective row (`_effective_row`, build_overview.py:770-783). Reproduction check: my selection gives **340** clean finals for static_feedback and **292** for combined_feedback, and the whole CSV contains exactly 632 `stopped_clean` rows (340 static + 292 combined, 0 test_feedback), none of which is a non-final row of its sample — selection and rows coincide 1:1.

* Headline reproduction before any correction: static_feedback ParEval-incorrect **47/340 = 13.8 %**, enhanced-failing **57/340 = 16.8 %** — identical to overview.md.
* "Enhanced-failing" = `enhanced_fail + enhanced_crash + enhanced_timeout + enhanced_runtime_error > 0` (build_overview.py:1080-1085; `build_failed` and gated specs do not count). Every clean final in both variants has both a correctness verdict and enhanced data (denominators equal cell sizes everywhere).

**Axis 1 (oracle-defective benchmark)** — `benchmark ∈ {50_stencil_xor_kernel, 45_sparse_la_sparse_solve}` (the two confirmed oracle defects; taken as given per brief).

**Axis 2 (tool-complete)** — *applicable static tools* per the pipeline's own scoping (thesis/evaluation/tool_config.py:55-79 `HARD_CAPABILITIES`/`STAGE_TOOLS`, narrowed identically by thesis/config/config.yaml:432-497): `compiler, gcc_analyzer, clang_tidy, cppcheck, infer` for every execution model, plus `llov` for omp only, plus `parcoach` for mpi only (6 applicable tools for omp/mpi, 5 for serial). The records confirm this scoping: out-of-scope tools carry `ran:false` with `error:"not applicable: '<em>' outside configured execution_models"` (llov: 452 mpi + 272 serial such records; parcoach: 365 omp + 273 serial, across all 1111 static_analysis records of the 7 run dirs). A clean final is **tool-complete** iff every applicable tool in the static_analysis record of its *effective* iteration has `ran:true` and `error:null`.

**Effective vs final iteration** — decision: completeness is evaluated on the *effective* (carry-forward, artifact-bearing) record, since that is the artifact whose "clean" verdict, correctness verdict and enhanced results are being counted. The decision is moot in pilot_001: for **all 632 clean finals the effective iteration equals the final iteration** (0 divergences; `na_reason` is empty/NA on all 1903 CSV rows — no `repair_unusable`/`artifact_missing` rows exist in this run).

## 2.1 Axis-2 verification of the briefed counts

Scanning `static_analysis.jsonl` of all 7 run dirs × 11 models (1111 records): real tool failures (`ran:true`, non-null `error`, always `num_blocking:0` — zero records have an error together with `num_blocking>0`):

| tool | error string | all records | among 340 static clean finals | among 292 combined clean finals |
|---|---|---|---|---|
| parcoach | `parcoach timed out` | 75 | **19** | 15 |
| parcoach | `clang -emit-llvm failed for the reduced TU` | 84 | **25** | 23 |
| llov | `llov clang exited with 1` (compile failure) | 61 | **22** | 21 |
| llov | `llov clang exited with 254` (plugin crash) | 20 | **8** | 6 |
| gcc_analyzer | `gcc -fanalyzer exited with 1` | 29 | 0 | 0 |
| infer | `infer exited with 1` | 28 | 0 | 0 |

The briefed split (74 = parcoach 19 timeouts + 25 reduced-TU failures, llov 22 compile failures + 8 plugin crashes) **verifies exactly** for static_feedback; no clean final has more than one erroring tool, and no gcc_analyzer/infer error lands on a clean final. Combined_feedback has **65** tool-incomplete clean finals (15+23+21+6), matching the briefed "65 affected clean endpoints". Incomplete clean finals are omp/mpi only (static: 44 mpi + 30 omp), concentrated on 20_histogram (21), 40_sort (19), 10_geometry_convex_hull (14), 35_search (11).

## 2.2 static_feedback: 2×2 decomposition of the 340 clean finals

Cells show n; clean-but-ParEval-incorrect; clean-but-enhanced-failing (all denominators = n; every sample has both measurements).

| | tool-complete | tool-incomplete | row marginal |
|---|---|---|---|
| **on defective benchmark** | n=41; incorrect 37/41 (90.2 %); enh-failing 22/41 (53.7 %) | n=3; incorrect 2/3; enh-failing 1/3 | n=44; incorrect 39/44 (88.6 %); enh-failing 23/44 (52.3 %) |
| **not on defective benchmark** | **n=225; incorrect 6/225 (2.7 %); enh-failing 20/225 (8.9 %)** | n=71; incorrect 2/71 (2.8 %); enh-failing 14/71 (19.7 %) | n=296; incorrect 8/296 (2.7 %); enh-failing 34/296 (11.5 %) |
| **column marginal** | n=266; incorrect 43/266 (16.2 %); enh-failing 42/266 (15.8 %) | n=74; incorrect 4/74 (5.4 %); enh-failing 15/74 (20.3 %) | n=340; incorrect 47/340 (13.8 %); enh-failing 57/340 (16.8 %) |

**Bottom-line static_feedback numbers (both-clean cell): clean-but-ParEval-incorrect 6/225 = 2.7 %, clean-but-enhanced-failing 20/225 = 8.9 %.**

Notes: (a) axis 1 does nearly all the correcting of the incorrect-rate (13.8 %→2.7 % along the row axis alone); (b) axis 2 *raises* the enhanced-failing rate in the excluded column (19.7 % vs 8.9 %) — tool-incompleteness correlates with benchmarks whose enhanced failures are themselves mostly the convex-hull artifact class (9 of those 14 are 10_geometry_convex_hull), so this exclusion removes disproportionately many artifact failures too. The two incorrect samples excluded only by axis 2 are `qwen3_coder_api__dense_la__00_dense_la_lu_decomp__omp` (llov exit 254) and `qwen3_coder_api__sort__40_..._by_magnitude__mpi` (parcoach reduced-TU failure); the defective+incomplete cell holds `gemini_36_flash__sparse_la__45...__mpi` and `openai_gpt56_sol__stencil__50...__mpi` (both parcoach timeouts).

## 2.3 combined_feedback: 2×2 decomposition of the 292 clean finals

| | tool-complete | tool-incomplete | row marginal |
|---|---|---|---|
| **on defective benchmark** | n=7; incorrect 0/7; enh-failing 0/7 | n=1; incorrect 0/1; enh-failing 0/1 | n=8; 0; 0 |
| **not on defective benchmark** | **n=220; incorrect 0/220 (0.0 %); enh-failing 18/220 (8.2 %)** | n=64; incorrect 0/64; enh-failing 10/64 (15.6 %) | n=284; 0/284; 28/284 (9.9 %) |
| **column marginal** | n=227; 0/227; 18/227 (7.9 %) | n=65; 0/65; 10/65 (15.4 %) | n=292; incorrect 0/292 (0.0 %); enh-failing 28/292 (9.6 %) |

**Bottom-line combined_feedback numbers (both-clean cell): clean-but-ParEval-incorrect 0/220 = 0.0 %, clean-but-enhanced-failing 18/220 = 8.2 %.** (Combined_feedback stops "clean" only when correctness tests also pass, so 0 incorrect is structural, not an accident.)

## 2.4 Per-sample classification: all 6 surviving clean-but-ParEval-incorrect samples (both-clean cell, static_feedback; combined has none)

Verdicts read from the effective iteration's `correctness.jsonl`; sources from the effective run dir's `sources/<sample_id>/generated-code.hpp`. Docker probes: see §2.7. **Result: 5 real functional defects, 1 measurement artifact.**

**1. `deepseek_v4_flash__geometry__10_geometry_convex_hull__omp__sample_0` (iter2, pilot_001__static_feedback__iter2) — REAL DEFECT (OpenMP task data-sharing).** Correctness: `validation_failed` at all of 1/2/4/8 threads, no mismatch lines (the hull driver's size check fails silently). Source lines 23-40: a task-parallel merge sort passes the vector as a reference parameter into `#pragma omp task` without `shared(arr)`; the implicit `firstprivate` on a reference type gives each task a private *copy* of the vector (probe 6: inside the task `arr.data()` differs from the parent's and a write through it is lost, GCC 13.3), so for n > THRESHOLD=1000 the array is never actually sorted (probe 4b: `is_sorted == FALSE` at 1/2/4/8 threads) and the monotone chain runs on unsorted input. Probe 4 (exact driver replication, same rand stream): baseline hull 18 points, generated "hull" **1162** points at TEST_SIZE=1024. Its enhanced tests all pass because every spec size is ≤ 8 — below the sort threshold, so the broken code path never runs (a size-coverage blind spot of the current specs).

**2. `deepseek_v4_flash__search__35_search_search_for_last_struct_by_key__omp__sample_0` (iter0, pilot_001) — REAL DEFECT.** Correctness: `MISMATCH expected=1016 got=1024` at every thread count. Source lines 17-27: `lastIdx` is initialised to `books.size()` as a "not found" sentinel, but the update guard is `if (i > lastIdx)` — never true since every index < size — so the function always returns 1024. Enhanced concurs: 18/18 runnable specs fail.

**3. `qwen36_35b_a3b__transform__55_transform_relu__mpi__sample_0` (iter0, pilot_001) — REAL DEFECT.** Correctness: pass at np=1; at np=2/4/8 `expected=0 got=<negative input>` from index n/np onward (e.g. index 512 at np=2, 257 mismatches). Source lines 16-26: each rank applies ReLU only to its own chunk of its own full copy and never communicates; the prompt requires "The final result is stored on rank 0" — the gather is missing, so rank 0's tail stays un-ReLU'd. Enhanced concurs (9/20 fail at the runner's fixed np=4, whenever an element outside rank 0's chunk is negative).

**4. `qwen37_max__dense_la__00_dense_la_lu_decomp__mpi__sample_0` (iter1, pilot_001__static_feedback__iter1) — REAL DEFECT.** Correctness: deterministic 260 056/262 144 mismatches at every np incl. 1, rel up to 1.83, first at index 1026 = row 2 col 2 of the 512×512 matrix. Source line 27: the elimination update reads `A[i*N + j] -= A[i*N + k] * A[k*N + k + j]` — the U factor is taken from row k at **column k+j** instead of column j; correct only for k=0, wrong from k=1 on (consistent with the first mismatch at row 2, col 2). Enhanced concurs: fails random specs at sizes 4/6/7 + one explicit_values(3); passes only trivial/degenerate sizes (0/1/2, all_same, alternating, extreme).

**5. `qwen3_coder_api__dense_la__00_dense_la_lu_decomp__serial__sample_0` (iter0, pilot_001) — MEASUREMENT ARTIFACT (absolute epsilon).** Correctness: 52/262 144 mismatches, shown rel ≈ 8.1-8.2e-9 at entry magnitudes ~1.4-1.8e5. Source: a Doolittle dot-product LU — mathematically identical factorisation to the baseline's right-looking elimination (drivers/cpp/benchmarks/dense_la/00_dense_la_lu_decomp/baseline.hpp), differing only in floating-point summation order, amplified by unpivoted-LU element growth. The driver compares with **absolute** epsilon 1e-3 (cpu.cc:76 `reportAndCompare(A_correct, A_test, 1e-3, A)`). Probe 3 recompiled the identical driver+source with `MISMATCH_REPORT_MAX=300000` and dumped **all** mismatches: exactly 52, **max relative difference 8.21e-9**. Any relative tolerance ≥ ~1e-8 clears it; this is the utilities.hpp absolute-epsilon artifact class.

**6. `qwen3_coder_api__reduce__25_reduce_xor__mpi__sample_0` (iter0, pilot_001) — REAL DEFECT (MPI API misuse).** Correctness: `runtime_error` (exit 10) at every np: "MPI_Allreduce: the reduction operation MPI_BXOR is not defined on the MPI_CXX_BOOL datatype … MPI_ERR_OP". Source line 16: `MPI_Allreduce(&local, &global, 1, MPI_CXX_BOOL, MPI_BXOR, …)` — the MPI standard defines only logical ops (LAND/LOR/LXOR) for MPI_CXX_BOOL; Open MPI aborts. (The algorithm additionally XOR-reduces full copies across ranks, the same semantic bug as class B below, but never gets that far.) Enhanced: all 20 specs crash.

## 2.5 Surviving clean-but-enhanced-failing set, per benchmark, with causes

**static_feedback both-clean cell (20 samples): 12 artifact / 8 real. combined_feedback both-clean cell (18 samples): 13 artifact / 5 real.**

| benchmark | samples (static / combined) | class | cause (one line) |
|---|---|---|---|
| 10_geometry_convex_hull serial+omp | 12 / 12 (claude_fable_5 ×2, claude_opus_5, gemini_31_pro, gemini_36_flash ×2, openai_gpt55 ×2, openai_gpt56_sol, qwen37_max ×2, qwen3_coder_api) | **ARTIFACT — known degenerate-spec class** | every failing spec is a degenerate pattern (all_same ×4 + all_zeros 1-2 per sample; a few duplicate_at/sorted_except_one/ascending; zero failures on `random`): the hull of identical/duplicate/collinear points is ambiguous, and the driver demands exact size+point-multiset equality with the baseline's own arbitrary degenerate answer (baseline emits *two* copies of the identical point for an all-same cloud; e.g. claude_fable_5's Jarvis march emits all n duplicates — neither is canonical) |
| 25_reduce_xor mpi | 5 / 5 (deepseek_v4_flash, deepseek_v4_pro, qwen36_35b_a3b, qwen37_max — each 13/20 fail; qwen3_coder_api in combined iter1) | **REAL — new defect class, not the audits' artifact class** | all five sources reduce the FULL vector on every rank and then combine across ranks (LXOR/BXOR of identical full-XORs, or SUM of identical counts mod 2) → result is constant-false whenever np is even; enhanced runs at np=4 (config.yaml:604 `mpi_ranks: 4`) and catches it; probe 2 reproduces FAIL at size 1024/np 4 and PASS at np 3 |
| 35_search_…_by_key omp | 1 / 0 (deepseek_v4_flash, 18/18 fail) | **REAL** | same sentinel bug as its ParEval failure (§2.4 #2) |
| 55_transform_relu mpi | 1 / 0 (qwen36_35b_a3b, 9/20 fail) | **REAL** | same missing-gather bug as its ParEval failure (§2.4 #3) |
| 00_dense_la_lu_decomp mpi | 1 / 0 (qwen37_max, 4/20 fail) | **REAL** | same k+j-index bug as its ParEval failure (§2.4 #4); passes only trivial/degenerate sizes |
| 05_fft_inverse_fft mpi | 0 / 1 (deepseek_v4_pro iter2, 3/20 fail) | **ARTIFACT — oracle domain violation (new artifact class)** | the oracle (`baseline.hpp` radix-2 Rosetta fft) is only valid for power-of-two N: probe 5 round-trip shows error 2.81 at N=3 and heap corruption (OOB write) at N=5/7 (those two got gated `baseline_incompatible`; N=3 slips through because it fails silently and the gate only compares baseline-to-itself); probe 7 diag: at the failing size-3 `ascending` spec the model's naive O(N²) DFT gives the mathematically correct j=0 value (mean = (0,0)) while the oracle says (-1/3,-1/3); the size-4 `extreme_values` failure is ±DBL_MAX inputs overflowing to inf/nan differently in two correct algorithms under the driver's absolute 1e-4 epsilon (three of four lanes additionally suppressed by the NaN-blind predicate) |

The reduce_xor class also exposes a **ParEval correctness blind spot** worth recording: all four base-run reduce samples have frozen verdict `pass` with `run_verdicts {'pass': 4}` at np=1/2/4/8 despite the even-np bug. Cause: the driver fills the test vectors from the deterministic unseeded `rand()` stream (utilities.hpp:205 "UNSEEDED rand() (as if srand(1))"; the reduce driver has no ENHANCED_FILL site, cpu.cc:77), and with numTries = MAX_VALIDATION_ATTEMPTS = 2 (utilities.hpp:25-26; neither run_correctness.py nor run_enhanced_tests.py overrides it) both size-1024 trial vectors happen to XOR to 0. Probe 1 computes the glibc parity stream and predicts, from first principles, exactly the observed enhanced spec outcomes (pass at sizes {0,1,2,7}, fail at {3,4,6,8,14,15,16,1023,1024,2046} after the 16-draw init offset) and PASS for the correctness geometry (offset 256, size 1024: parities 0,0); probe 2 confirms by executing the actual binaries.

## 2.6 What survives after both corrections — honest summary

* static_feedback: clean-but-ParEval-incorrect **2.7 % (6/225)**, of which 5 are genuine model bugs and 1 is an absolute-epsilon artifact (truly-defective share 5/225 = 2.2 %). Clean-but-enhanced-failing **8.9 % (20/225)**, of which 8 are genuine (3.6 %) and 12 are the convex-hull degenerate-spec artifact (5.3 %).
* combined_feedback: clean-but-ParEval-incorrect **0.0 % (0/220)** (structural); clean-but-enhanced-failing **8.2 % (18/220)**, of which 5 genuine (2.3 %) and 13 artifacts (12 hull + 1 fft-oracle).
* The corrected phenomenon is therefore real but small, and — beyond the two briefed axes — the pilot has two additional measurement issues surfaced here: (i) the fft oracle is invalid for non-power-of-two enhanced sizes and the baseline gate cannot catch the silent case (N=3); (ii) the unseeded-rand + numTries=2 validation makes ParEval correctness deterministically blind to the even-np reduce_xor bug class, while conversely the enhanced specs' small sizes (≤8 for hull) are blind to the >1000-element convex-hull sort bug. Neither fix belongs to Phase 0; both belong on the remediation list.

## 2.7 Probe inventory (everything executed)

Scripts and outputs live in the session scratchpad `…\scratchpad\task2\` (`explore_csv.py`, `scan_errors.py`, `main_analysis.py` → `clean_finals.json`, `pull_correctness.py`, `pull_enhanced2.py`, `survivor_specs.py`, `spot_checks.py`, `details.py`; C++ probes under `probe\`). Docker (image `pareval-thesis:latest`, GCC 13.3 / Open MPI; repo mounted read-only, scratch writable):

```
docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" -v "<scratch>/task2:/scratch" pareval-thesis:latest bash -c "… bash /scratch/probe/run_probes.sh"   # probes 1-5
… run_probes2.sh   # probe 1 full, 4b (sort isolation), 5 per-N
… run_probes3.sh   # probe 6 (task data-sharing), 7 (fft enhanced specs)
… fft_diag build+run  # per-element oracle-vs-model dump for the two failing fft specs
```

Probe compile lines mirror the pipeline exactly (build_config.py: `g++/mpicxx -std=c++17 -O3 -DUSE_<EM> -DDRIVER_PROBLEM_SIZE=(1<<8)` for correctness geometry; `-DDRIVER_PROBLEM_SIZE=(1<<4) -DENHANCED_TEST_SIZE=<n> [-DENHANCED_RUNTIME_FILL + ENHANCED_FILL_* env]` for enhanced geometry, per run_enhanced_tests.py:285-334 and 375-396). No repository file was modified; no fix was implemented.

> **Adversarial verification: CONFIRMED.** Full independent re-derivation (overview.csv + stage JSONLs + 4 own Docker probes) matched every count, rate and classification. Three peripheral figures were corrected without affecting any conclusion: the fft round-trip error measures 1.18/1.91 on the actual failing spec fills (not 2.81, which came from a different probe fill; the invalid-oracle claim itself reconfirmed — model-vs-truth error 0, oracle-vs-truth up to 1.12); the hull probe reproduces as 1156-vs-16 points at n=1024 (mechanism identical); the hull enhanced-spec size bound is 7, not 8.


---

# Task 3 — Rounding-only correctness failures (correctness stage, whole pilot)

## Bottom line

**The correctness stage has exactly 10 rounding-only `validation_failed` verdicts out of 358 (2.8%), and all 10 are one single mechanism instance**: model `qwen3_coder_api` on benchmark `dense_la/00_dense_la_lu_decomp`, serial + omp, replicated across 5 run dirs (base + test_feedback iter1/2 + combined_feedback iter1/2). Every one was **confirmed by full re-execution in Docker** — no row is left in a "likely/undecidable" bucket. All other `validation_failed` records are either gross failures (max recorded rel ≥ 7.8e-3) or come from bespoke boolean validators where rounding is structurally implausible. So: **not "none", not a broad tolerance problem — a handful, fully concentrated in one benchmark×model pair.**

## 0. Receipt verification of the known instance

`thesis/results/intermediate/pilot_001/qwen3_coder_api/correctness.jsonl`, sample `qwen3_coder_api__dense_la__00_dense_la_lu_decomp__serial__sample_0`: verdict `validation_failed`, run stdout contains `MISMATCH index=205201 expected=182070.86024185043 got=182070.86173061817 rel=8.18e-09 input=9.2655473664708197`, then indices 205202 (rel=8.17e-09) and 205206 (rel=8.14e-09), then `MISMATCH_SUMMARY shown=3 total=52`. The omp record has 4 runs (num_threads 1/2/4/8), each `mismatch_total=52`, same 3 recorded rels.

**Correction to the briefed receipt**: the record does NOT contain 52 rel values — only the first 3 plus a total (see §1). "ALL ~8.1e-9" was undecidable from records alone; my re-execution (§3) proved it true.

Epsilon receipt: `drivers/cpp/benchmarks/dense_la/00_dense_la_lu_decomp/cpu.cc:76` — `reportAndCompare(A_correct, A_test, 1e-3, A)`; the predicate in `drivers/cpp/utilities.hpp` (`reportAndCompare`, ~line 315) is **absolute**: `std::abs(x - y) > epsilon`. The reported `rel` is `|a-b| / max(|a|,|b|, DBL_MIN)` (`mismatchRelDiff`, utilities.hpp:241-260). Validation matrix is 512×512 (`ENHANCED_TEST_SIZE_DEFAULT(512)`, cpu.cc:51; correctness compiles don't define `ENHANCED_TEST_SIZE`, so the default applies — `drivers/cpp/enhanced-fill.hpp:76-78`). At magnitudes ~1.8e5–2.3e5, rel 8.2e-9 → abs diff ~1.5e-3–1.9e-3 > 1e-3.

## 1. Methodological gate: records ARE truncated

`thesis/evaluation/run_correctness.py:212-227` compiles with `-DMISMATCH_REPORT_MAX=<k>` where k = `stages.repair.feedback.mismatch_report_max_indices` (default 3); `drivers/cpp/utilities.hpp:213-214` defaults to 3. Every pilot record I inspected shows `shown=3` (or fewer). The JSONL `mismatches` array holds only the printed lines; `mismatch_total` holds the true per-run count. So "all mismatches rel < 1e-6" is **not decidable from records alone whenever `mismatch_total > len(mismatches)`**.

## 2. Full census (script: `scratchpad/task3/scan_correctness.py`, `categorize.py`; host python, stdlib)

Population: every `correctness.jsonl` under the 7 run dirs `pilot_001`, `pilot_001__{static,test,combined}_feedback__iter{1,2}` in `thesis/results/intermediate/`.

- **1111 correctness records** total: pass 710, **validation_failed 358**, build_failed 29, runtime_error 12, timeout 2.
- The 358 validation_failed decompose (a record's rels = all recorded mismatches over all its failing runs; rel taken from the stored field, recomputed from full-precision expected/got as fallback):

| category | n | decidable? | outcome |
|---|---|---|---|
| E: zero recorded mismatches (bespoke boolean validator, stdout just `Validation: FAIL`) | 196 | no rel data exists | rounding structurally implausible (see §4) |
| B: complete (recorded == mismatch_total on every failing run), some rel ≥ 1e-6 | 5 | yes | NOT rounding-only |
| C: truncated, but some recorded rel ≥ 1e-6 | 147 | yes (one large rel suffices) | NOT rounding-only |
| D: truncated, ALL recorded rel < 1e-6 | 10 | **no → re-executed** | ALL confirmed rounding-only (§3) |
| A: complete and all rel < 1e-6 | 0 | yes | — |

Decidability quantification: of the 162 records that have mismatch data, only 5 are complete; 157 are truncated. Truncation blocked the verdict only for the 10 category-D rows.

Threshold robustness: across all 152 decided-NOT rows, the **minimum** max-recorded-rel is **0.0078125** (no row falls in [1e-6, 1e-3)). The pilot's mismatch rel distribution is sharply bimodal: ~8e-9 (the 10 D rows) vs ≥ 7.8e-3 (everything else). The 1e-6 cut is insensitive to ±3 orders of magnitude.

4 records contain NaN rels (deepseek_v4_flash LU **mpi** base run: 956 mismatches incl. NaNs; qwen36_35b_a3b sparse_la/45 mpi in base + static iter1/2) — NaN outputs, classified NOT rounding-only (in B/C).

## 3. Re-execution of the 10 candidates (Docker, full mismatch reporting)

The 10 D rows are `qwen3_coder_api__dense_la__00_dense_la_lu_decomp__{serial,omp}__sample_0` in run dirs `pilot_001`, `pilot_001__test_feedback__iter1/2`, `pilot_001__combined_feedback__iter1/2`. Sources (`.../sources/<sample_id>/generated-code.hpp`) have **8 distinct md5s** (serial: 3 distinct — test iter1 = test iter2 = combined iter2; omp: 5 distinct).

Commands (script `scratchpad/task3/rerun.sh`; repo mounted read-only, nothing written into the repo):

```
MSYS_NO_PATHCONV=1 docker run --rm -u 0 \
  -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" -v "<scratchpad>/task3:/scratch" \
  pareval-thesis:latest bash /scratch/rerun.sh
# serial, mirrors run_correctness.py compile_sample / build_config.base_command:
g++ -std=c++17 -O3 -DUSE_SERIAL -I /repo/drivers/cpp -I /repo/drivers/cpp/models -I <srcdir> \
  "-DDRIVER_PROBLEM_SIZE=(1<<8)" -DMISMATCH_REPORT_MAX=1000000 \
  /repo/drivers/cpp/models/serial-driver.cc \
  /repo/drivers/cpp/benchmarks/dense_la/00_dense_la_lu_decomp/cpu.cc -o bin ; ./bin 1
# omp: g++ ... -fopenmp -DUSE_OMP ... models/omp-driver.cc ...; OMP_NUM_THREADS=$nt ./bin $nt  (nt = 1,2,4,8)
```

The ONLY deviation from the pipeline compile is raising `MISMATCH_REPORT_MAX` 3 → 1e6 (reporting bound only; comparison unchanged). 10 compiles, **25 executions** (5 serial ×1 niter run, 5 omp ×4 thread counts), all exit 0, all `Validation: FAIL`.

**Result (parser `analyze_reruns.py`, rel recomputed at full precision from the printed max_digits10 expected/got): every execution shows `MISMATCH_SUMMARY shown=52 total=52`; all 52 rels lie in [8.094e-09, 8.215e-09]; count of rel ≥ 1e-6 is 0 in every run.** Fidelity check: the base-serial re-run's first 3 mismatch lines are byte-identical to the frozen record (indices 205201/205202/205206, same expected/got/rel), and omp totals match the record (52 per run × 4 runs = 208). Inputs are deterministic (unseeded `rand()`, utilities.hpp:204-207), so this is a faithful replay, not a fresh sample.

Mechanism: the generated code (all variants) implements Doolittle/dot-product LU (`sum += A[k*N+p]*A[p*N+j]` inner products) while `baseline.hpp` uses right-looking Gaussian elimination — mathematically identical, different floating-point summation order. At N=512 with |values| up to ~2.3e5, the abs-1e-3 epsilon corresponds to an effective rel tolerance of ~4e-9, tighter than legitimate reordering noise. The LU **mpi** sample of the same model **passed** (base run, static iter1, combined iter1), so only serial+omp are affected.

## 4. The 196 no-mismatch-data rows (undecidable by rel, but rounding implausible)

Benchmarks: `stencil/50_stencil_xor_kernel` ×184, `sort/40_..._by_magnitude` ×7, `geometry/10_geometry_convex_hull` ×5 (exec split for all 196: serial 60 / omp 64 / mpi 72). Their `validate()` uses hand-rolled boolean loops, not `reportAndCompare`, so no MISMATCH lines exist (checked: 0 records anywhere have MISMATCH text in stdout with an empty `mismatches` array — no parse failures):
- stencil/50 (cpu.cc ~line 80): exact `int != int` on an integer XOR grid — rounding impossible; failures are the known 4- vs 8-neighbor oracle defect (out of scope here).
- sort/40 (cpu.cc:88): positional `|correct[i]-test[i]| > 1e-6` on sorted complex arrays; sorting only permutes exact input values, so any positional mismatch is O(1) — tie-ordering/comparator semantics, not tolerance.
- geometry/10 (cpu.cc:96-109): hull-size equality + per-coordinate 1e-6 on sorted vertex lists; hull vertices are copied input points (no arithmetic on outputs), so failures are different vertex sets (e.g. collinear policy), not rounding.

I report these as "no per-element data recorded; rounding-only excluded on structural grounds", distinct from the decided-by-rel population.

## 5. Deliverable counts

**Rounding-only validation_failed records (correctness stage, whole pilot): 10 of 358** — all decided (0 left undecidable).

Per benchmark: `dense_la/00_dense_la_lu_decomp` = 10; every other benchmark = 0.
Per execution model: serial = 5, omp = 5, mpi = 0.
Per model: `qwen3_coder_api` = 10; all other models = 0.

Sample_ids (run dir → sample_id):
- pilot_001 → `qwen3_coder_api__dense_la__00_dense_la_lu_decomp__serial__sample_0`
- pilot_001 → `..__omp__sample_0`
- pilot_001__test_feedback__iter1 → `..__serial..` and `..__omp..`
- pilot_001__test_feedback__iter2 → `..__serial..` and `..__omp..`
- pilot_001__combined_feedback__iter1 → `..__serial..` and `..__omp..`
- pilot_001__combined_feedback__iter2 → `..__serial..` and `..__omp..`

(static_feedback iter1 re-ran only the LU **mpi** sample, which passed; the serial/omp LU samples are absent from static_feedback iter1/iter2 correctness files — not re-generated in that variant.)

Overview.csv view: `thesis/results/analysis/pilot_001/overview.csv` (1903 rows; correctness_verdict: 490 validation_failed — inflated vs 358 records because iteration-0 base results appear once under each of the 3 variants). The 10 records surface as **14 overview rows**: 2 exec × 3 variants at iteration 0 (`is_shared_initial=true`) + 2 exec × {test iter1, test iter2, combined iter1, combined iter2}.

## 6. Enhanced-stage sanity check (separate population, brief)

Across all 7 run dirs' `enhanced_tests.jsonl`: 22,220 records (pass 17,523, fail 2,072, crash 663, baseline_incompatible 752, numerically_unstable 528, build_failed 518, timeout 164). Of the 2,072 fails, 301 carry mismatch data; **0** have all recorded rel < 1e-6 (complete or truncated). The prior audit's "no rounding candidates in the enhanced stage" holds, and — as briefed — it says nothing about the correctness stage, which does have the 10 cases above.

## 7. Interpretation for the fix phase (no fix applied here)

The correctness stage's tolerance problem is real but surgically narrow: one benchmark whose absolute epsilon (1e-3) is ~5 orders of magnitude tighter in relative terms than its output magnitude warrants. Consequences in the pilot: the same rounding-only false negative consumed 4 repair iterations for qwen3_coder_api (test iter1/2, combined iter1/2 — repair cannot "fix" a tolerance artifact), and misclassifies 2 sample slots (serial, omp) as incorrect. The other three dense_la/00 failures in the pilot are genuine (qwen37_max mpi: 1,040,224 mismatches, max rel 1.83, base + static iter1; deepseek_v4_flash mpi: 956 mismatches incl. NaN, base run) — a tolerance change at any sane level would not flip them.

> **Adversarial verification: CONFIRMED.** All counts re-derived (1111 records; 358 validation_failed; partition 196/5/147/10/0) and the 10 candidates independently re-executed in Docker with the verifier's own scripts — same 52/52 mismatches, all rel < 1e-6. One labeling clarification: the "min max-recorded-rel = 0.0078125" figure requires recomputing rel from expected/got strings (it comes from 5 search/35 omp rows whose integral mismatches carry no rel field); using literal recorded rel fields the smallest above-threshold value is 0.263. Under either definition the [1e-6, 1e-3) band is empty and the conclusion stands.


---

# Task 4 — Oracle runtime of the 21 large frozen specs vs the enhanced-stage walls

## What was measured and how (receipts)

Two faithful replicas were built for every spec, from copies of `drivers/` in the session scratchpad (`.../scratchpad/task4/`; repo untouched), executed inside Docker image `pareval-thesis:latest` (g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 — first line of the harness console), sequentially, each run capped by `/usr/bin/timeout -k 5 300` and executed 2x:

- **G = gate replica**: exactly `thesis/enhanced_tests/baseline_selftest.py::compile_and_run` — `g++ -std=c++17 -O1 -DUSE_SERIAL -DDRIVER_PROBLEM_SIZE=(1<<4)` + `spec_defines(spec)` (compile-define fill path) + `MISMATCH_REPORT_MAX=3`, sources `drivers/cpp/models/serial-driver.cc` + the benchmark's `cpu.cc`, run as `<bin> 1`. The pipeline's wall for this binary is **30 s**, hardcoded (`baseline_selftest.py:50 RUN_TIMEOUT = 30`, used at line 305; NOT the configurable `run_timeout_seconds`). Exceeding it → gate verdict "hang" → `run_enhanced_tests.py::process_sample` records `baseline_incompatible` for every sample.
- **M = model-run replica**: exactly `run_enhanced_tests.py::compile_argv` for a serial sample — `g++ -std=c++17 -O3 -DUSE_SERIAL -DDRIVER_PROBLEM_SIZE=(1<<4) -DENHANCED_TEST_SIZE=<n> -DMISMATCH_REPORT_MAX=3 -DENHANCED_RUNTIME_FILL`, fill configured per spec via `spec_runtime_env()` environment variables (`ENHANCED_FILL_PATTERN` etc.), run as `<bin> 1`. The pipeline's wall is **60 s** (`thesis/config/config.yaml:613 run_timeout_seconds: 60` under `enhanced_tests:` at line 539; confirmed frozen in `thesis/results/intermediate/pilot_001/claude_fable_5/enhanced_tests_summary.json` `effective_config.run_timeout_seconds: 60.0`).

The candidate slot (`generated-code.hpp`) forwards to the baseline `correct*()`, generated by importing the pipeline's own `baseline_selftest.build_wrapper` (not reimplemented) with the serial prompts from `prompts/generation-prompts.json`. All 14 wrappers built. The binary therefore executes: init(16) + validate = **2 trials x (baseline + baseline-as-candidate + comparison)** (`MAX_VALIDATION_ATTEMPTS` defaults to 2, `drivers/cpp/utilities.hpp:25-27`) + 1 timed compute + 1 timed best at N=16 (negligible) — the closest executable proxy for the gating question. `spec_defines`/`spec_runtime_env`/`MISMATCH_REPORT_MAX` resolved by importing `thesis/enhanced_tests/specs.py` and `thesis/config/load_config` (mismatch_k = 3, `config.yaml:722`).

Artifacts: `.../scratchpad/task4/{generate_harness.py, run_all.sh, manifest.json, results.csv, runs/, build/}` and the console transcript in the background-task output file. 49 builds (21 G + 20 M groups + 8 scaling siblings), 98 runs; **0 build failures, every run exited 0 with `Validation: PASS`** — no spec was untimeable, and the oracle self-agrees on every input (no crash/validate-fail surprises among the 21).

## Per-spec results (wall seconds, rep1/rep2; from results.csv)

| # | benchmark | size | pattern (params) | G gate -O1 (30 s wall) | M model -O3 (60 s wall) | verdict |
|---|-----------|------|------------------|------------------------|--------------------------|---------|
| 0 | fft/05_fft_inverse_fft | 4096 | all_zeros | 0.012 / 0.010 | 0.014 / 0.011 | OK |
| 1 | histogram/20_histogram_pixel_histogram | 256 | ascending [0,255] | 0.011 / 0.010 | 0.011 / 0.010 | OK |
| 2 | reduce/27_reduce_average | 4096 | spike_at k=0 [-1,1] | 0.010 / 0.010 | 0.015 / 0.013 | OK |
| 3 | reduce/29_reduce_sum_of_min_of_pairs | 4096 | all_same [DBL_MAX,DBL_MAX] | 0.010 / 0.012 | 0.011 / 0.011 | OK |
| 4 | search/39_search_xor_contains | 4096 | ascending [0,4095] | 0.012 / 0.012 | 0.016 / 0.013 | OK |
| 5 | **dense_la/01_dense_la_solve** | **4096** | extreme_values | **56.337 / 54.820** | **58.557 / 59.701** | **FAILS BOTH WALLS** |
| 6 | graph/15_graph_edge_count | 1023 | all_zeros [0,1] | 0.041 / 0.043 | 0.060 / 0.057 | OK |
| 7 | graph/15_graph_edge_count | 4096 | all_zeros [0,1] | 0.520 / 0.518 | 0.636 / 0.611 | OK |
| 8 | graph/16_graph_largest_component | 1024 | random | 0.061 / 0.055 | 0.057 / 0.053 | OK |
| 9 | graph/16_graph_largest_component | 4096 | random | 0.689 / 0.686 | 0.761 / 0.750 | OK |
| 10 | graph/17_graph_highest_degree | 1024 | random | 0.031 / 0.029 | 0.037 / 0.052 | OK |
| 11 | graph/17_graph_highest_degree | 4096 | random | 0.348 / 0.336 | 0.432 / 0.498 | OK |
| 12 | graph/18_graph_count_components | 1024 | random | 0.054 / 0.049 | 0.062 / 0.061 | OK |
| 13 | graph/18_graph_count_components | 4096 | random | 0.662 / 0.683 | 0.722 / 0.839 | OK |
| 14 | graph/19_graph_shortest_path | 1024 | random | 0.038 / 0.038 | 0.051 / 0.045 | OK |
| 15 | graph/19_graph_shortest_path | 4096 | random | 0.449 / 0.487 | 0.411 / 0.394 | OK |
| 16 | histogram/23_histogram_first_letter_counts | 4096 | random | 0.013 / 0.012 | 0.012 / 0.014 | OK |
| 17 | reduce/25_reduce_xor | 1023 | random | 0.013 / 0.010 | 0.015 / 0.013 | OK |
| 18 | reduce/25_reduce_xor | 1024 | random | 0.015 / 0.014 | 0.011 / 0.012 | OK |
| 19 | search/39_search_xor_contains | 4096 | spike_at k=4095 | 0.012 / 0.011 | 0.014 / 0.017 | OK |
| 20 | sort/44_sort_sort_non-zero_elements | 4096 | random [-1000,1000] | 0.009 / 0.009 | 0.011 / 0.010 | OK |

Worst non-dense_la wall: 0.839 s (graph/18@4096, M rep2) — **71x headroom** to 60 s, 35x to the 30 s gate. Timeout at 300 s was never reached by anything.

## Scaling sanity siblings (config M, random fill)

dense_la/01: 64 → 0.016/0.010 s; 512 → 0.078/0.083 s; 1024 → 0.499/0.508 s; 2048 → 5.704/5.595 s; 4096 → 58.6/59.7 s. Step ratios 1024→2048 = 11.2x, 2048→4096 = 10.5x — clean cubic-plus-memory scaling; 4096 is exactly where the curve crosses the walls, and a size-2048 replacement would run ~5.7 s (oracle-as-candidate), comfortably inside both walls. graph/19 @64/512: 0.013–0.018 s; graph/16 @64/512: 0.011–0.020 s.

## Cross-validation against frozen pilot data

- 6 of the 21 specs were in fact already exercised in pilot_001 (their benchmarks are among the pilot's 12; see premise note): their frozen `duration_seconds` match my replicas — e.g. graph/15@4096 serial: pilot med 0.535 s / max 1.303 s (n=11) vs my 0.611–0.636 s; fft/05@4096 all_zeros serial: pilot med 0.002 s; reduce/25@1023/1024 serial med 0.001 s. Source: `thesis/results/intermediate/pilot_001*/*/enhanced_tests.jsonl`, keyed by `spec_key`.
- Calibration re-derived from the same files: 8434 non-timeout MPI runs with duration, p50 = 0.337 s, p90 = 0.389 s, p99 = 1.575 s, max = 3.868 s (matches the task's given figures exactly). Serial: 5058 runs, p99 = 0.027 s, max = 1.594 s.
- No large-size gate evidence pre-exists: `thesis/results/cache/enhanced/baseline_selftest.jsonl` covers sizes 0/1/2/7 only (60 rows each). These measurements are the first at the large sizes.

## Verdicts against the two failure modes

**(a) oracle run > 60 s → silently gated:** No spec's oracle run exceeds 60 s outright. BUT the spec-killing wall is not 60 s — it is the baseline gate's **hardcoded 30 s at -O1** (`baseline_selftest.py:50`), which runs first and is not configurable via `run_timeout_seconds`. **dense_la/01_dense_la_solve@4096 measures 54.8–56.3 s there → the gate returns "hang" → the spec is recorded `baseline_incompatible` for every sample of every model and contributes nothing.** That is exactly failure mode (a)'s outcome, triggered at 30 s/-O1 instead of 60 s/-O3. No other spec comes within a factor of 35 of the gate wall.

**(b) 40–55 s → legitimately slower candidate misrecorded as hang:** Only dense_la/01@4096. Its M-replica (fill + 2x(oracle + oracle-as-candidate) + comparison) measures **58.6 / 59.7 s — straddling the 60 s wall within run-to-run noise**. The oracle side alone consumes ~29.5 s of the 60 s budget (2 oracle executions per validate). Derived (labeled estimate, from the measured 59.1 s mean / 4 oracle executions): an instant correct candidate → ~30 s wall; a candidate at half oracle speed → ~44 s (mid hang-adjacent band); a candidate at 1.0x oracle speed → ~59 s; at 1.05x → over the wall. So if the spec were ever let past the gate (e.g. by raising only the gate timeout), essentially every legitimate candidate would land in the 44–60+ s band and correct-but-not-faster-than-oracle solutions would be misrecorded as timeouts. For all other 20 specs, even a 10x-slower-than-oracle candidate stays under ~5 s.

## Conclusion

**60 s holds — only if dense_la/01_dense_la_solve@4096 (pattern extreme_values, the single size-4096 spec of that benchmark in specs.jsonl) is dropped or resized.** The list of offending specs is exactly that one. The other 20 large specs pass both walls with ≥35x (gate) / ≥71x (run) headroom, and their oracle behavior is clean (all PASS). Remediation options, in measured order of safety: (1) drop the spec; (2) resize to 2048 → ~5.7 s full oracle-pair run, >10x headroom under 60 s and inside the 30 s gate; (3) raising walls is NOT a one-knob fix: `run_timeout_seconds` does not govern the gate — the hardcoded 30 s in `baseline_selftest.py` would also have to change, and safety at 4096 would need ≥180 s on both walls.

## Caveats

- Host is not a quiet room (Windows Docker Desktop, same machine as the pilot); rep-to-rep deltas were ≤4 % on the dense runs and up to ~35 % on the (irrelevant) sub-0.1 s runs. The dense_la/01 conclusion does not depend on ±10 % accuracy: 55–60 s against a 30 s gate and a 60 s wall is decisive either way.
- Measurements are serial (the task's ask; the gate is serial by design). For omp/mpi model runs the same 60 s wall also covers `mpirun`/thread startup (pilot mpi p50 0.337 s) — immaterial at these magnitudes.
- The M replicas of the two search/39@4096 specs share one binary (one build per (sample,size) group), exactly like the pipeline.

---

# Task 5 — Scope of the gcc_analyzer libstdc++ path filter

## 1. What "path" means in these records (finding structure)

Every gcc_analyzer finding in all 7 runs has exactly one key set — verified programmatically across all 6,585 gcc_analyzer finding objects (blocking and non-blocking) in `thesis/results/intermediate/pilot_001*/*/static_analysis.jsonl` (schema `static_analysis.v2`):

```
{tool, check_id, severity, message, file, line, column, blocking, low_confidence}
```

There is **no path/trace array**. The only per-finding text is `message` — the one-line GCC diagnostic text with the `[-Wanalyzer-*]` flag stripped (parsed by `parse_gcc_clang_diagnostics`, regex `GCC_CLANG_DIAGNOSTIC` at `thesis/evaluation/tools.py:91-99`; `note:` lines are dropped because kept findings must have `check_id.startswith("-Wanalyzer")`, tools.py ~line 399-414). The full analyzer output including the event path exists only in the tool-level `raw_stderr`, which is **truncated to 8,000 chars at serialization** (`thesis/evaluation/framework.py:104-105`, `self.raw_stderr[:8000]`); findings were parsed from the *untruncated* stderr, so the stored findings list of each record is complete even where `raw_stderr` is cut off (confirmed: `openai_gpt55__scan__30_scan_prefix_sum__mpi__sample_0` base run has a blocking null-deref at line 56 whose warning text does not appear in its 8,000-char `raw_stderr`, yet the finding is stored).

**Operational definitions used below.** "Path filter matches the finding itself" (bucket a) = `message` contains any of `_Vector_base`, `_M_impl`, `_M_start`, `_M_finish` (substring; `std::_Vector_base` is subsumed). Bucket (b) = not (a), but some gcc_analyzer finding of the same record (any severity/blocking status) has a token-bearing message, split into **b_line** (token finding at the same `(file, line)`) and **b_sample** (token finding elsewhere in the same sample record). Bucket (c) = no token-bearing finding anywhere in the record.

## 2. Bucket counts (all gcc_analyzer BLOCKING findings, 7 run dirs)

844 blocking gcc_analyzer findings total (804 after dedup on (run, sample, check_id, line, column, message); dup excess is mostly malloc-leak 47→26 and uninit 118→104). Script: `scratchpad/task5/buckets.py`.

### Overall (all 7 runs)

| check_id family | a (self) | b_line | b_sample | c (none) | sum |
|---|---|---|---|---|---|
| -Wanalyzer-null-dereference | 0 | 177 | 65 | 142 | 384 |
| -Wanalyzer-possible-null-dereference | 271 | 0 | 0 | 21 | 292 |
| -Wanalyzer-use-of-uninitialized-value | 2 | 32 | 52 | 32 | 118 |
| -Wanalyzer-malloc-leak | 20 | 0 | 0 | 27 | 47 |
| -Wanalyzer-out-of-bounds | 0 | 0 | 3 | 0 | 3 |
| **TOTAL** | **293** | **209** | **120** | **222** | **844** |

### Per run

| run | a | b_line | b_sample | c | sum |
|---|---|---|---|---|---|
| pilot_001 (iter 0) | 72 | 50 | 28 | 31 | 181 |
| static_feedback iter1 | 46 | 38 | 19 | 36 | 139 |
| test_feedback iter1 | 40 | 28 | 18 | 15 | 101 |
| combined_feedback iter1 | 43 | 29 | 15 | 35 | 122 |
| static_feedback iter2 | 27 | 20 | 16 | 51 | 114 |
| test_feedback iter2 | 18 | 13 | 6 | 12 | 49 |
| combined_feedback iter2 | 47 | 31 | 18 | 42 | 138 |

Iteration aggregates: iter0 = 72/50/28/31 (181); iter1 = 129/95/52/86 (362); iter2 = 92/64/40/105 (301).

**Briefed numbers re-derived and confirmed:** at iteration 0 there are exactly 80 blocking `-Wanalyzer-null-dereference` findings; 43 sit on the same line as a token-naming finding, 14 more in the same sample, 23 name libstdc++ nowhere. (Also matched the briefed read example: `openai_gpt55__scan__30_scan_prefix_sum__mpi__sample_0`, one blocking null-deref at line 56, message `dereference of NULL '0' [CWE-476]`, no token finding in the record.)

**Headline: the planned plain path filter catches 293/844 = 34.7% of blocking findings (273/794 = 34.4% within the null-deref/possible-null/uninit demotion scope). Adding same-line co-occurrence reaches 502/844 (59.5%); adding same-sample reaches 622/844 (73.7%). 222 findings (26.3%) are out of reach of any co-occurrence rule.**

## 3. What bucket (c) is (222 findings, 148 distinct (run,sample) pairs)

Message-class tabulation (script `cmsg.py`/`cexpr.py`):

- **142 null-deref — every single one has message exactly `dereference of NULL '0' [CWE-476]`.** (In fact all 384 blocking null-derefs dataset-wide quote `'0'`.)
- **21 possible-null-deref**: 15 quote an `operator new [](…)` expression, 3 quote `<unknown>`, 3 name a raw `new[]` pointer by name (`localB`, `pivot`×2 — all in `openai_gpt55__sparse_la__45…__mpi`, static_feedback iter2).
- **32 uninit**: 19 `*<unknown>`, 8 libstdc++ iterator internals (`*__it1$_M_current.Point::x`, `*__i$_M_current.Point::x`), 2 `*<unknown>.Point::x`, 1 `*__first.Point::x`, 1 `num_threads`, 1 `<unknown>`.
- **27 malloc-leak**: 24 `leak of 'operator new [](…)'`, 3 `leak of '<unknown>'` (all in iter2 runs; malloc-leak is outside the planned demotion scope — see §6).

### Representative source reads (12 samples, 47 bucket-c findings inspected)

All paths under `thesis/results/intermediate/<run>/<model>/sources/<sample_id>/generated-code.hpp`:

1. **pilot_001 / claude_fable_5__stencil__50_stencil_xor_kernel__mpi** — null-deref '0' @51: `recvCounts[r] = (int)(rRows * N);` two lines after `std::vector<int> recvCounts(size), displs(size);` (line 47). Vector-allocation FP.
2. **pilot_001 / deepseek_v4_pro__stencil__50…mpi** — '0' @56 `local_output[r*N_int+c] = …` and @70 `recvcounts[i] = rows_i*N_int;` (vectors declared lines 65-66). Same FP.
3. **pilot_001 / gemini_36_flash__transform__55_transform_relu__mpi** — '0' @32: `recvcounts[r] = chunk + …` after `std::vector<int> recvcounts(comm_size);` @28. Same FP.
4. **pilot_001 / deepseek_v4_flash__sparse_la__45…serial** — '0' @31: `std::fabs(dense[col*N+col])` on a `std::vector<double>`. Same FP.
5. **pilot_001 / gemini_36_flash__fft__05_fft_inverse_fft__mpi** — '0' @77: `recvcounts[r] = …` after `std::vector<int> recvcounts(size), displs(size);` @72. Same FP.
6. **pilot_001 / gemini_31_pro__geometry__10_geometry_convex_hull__omp** — uninit `*__it1$_M_current.Point::x` ×2 @23: the comparator lambda used by `std::sort` over `std::vector<Point> local_points(points.begin()+start, points.begin()+end)` (line 43); analyzer loses provenance of range-constructed elements and flags the read via sort's iterator internals. FP; message names `_M_current` (a libstdc++ internal NOT in the planned 4-token list).
7. **pilot_001 / qwen36_35b_a3b__scan__30_scan_prefix_sum__omp** — uninit `num_threads` @14 (the `#pragma omp parallel` line): `int num_threads;` @13 is assigned by every thread inside the region (`num_threads = omp_get_num_threads();` @16) before its first read @19. The "use" is the OMP-outlining capture of the not-yet-written variable. Not a memory-safety defect (though a real benign-race style smell); FP as stated.
8. **pilot_001 / gemini_31_pro__sparse_la__45…mpi** — uninit `*<unknown>` @81: `xi -= flat_M[…] * x[j];` — back-substitution reading `x[j]` elements that are filled at runtime by earlier iterations/`MPI_Bcast`, invisible to the analyzer. FP.
9. **combined iter2 / openai_gpt55__scan__30…mpi** (12 findings) — `int *counts = new int[…]; int *displs = new int[…];` @48-49; possible-null @55-56 on `counts[p]`/`displs[p]` quotes `operator new []((…)*4)`, and 10 malloc-leak findings @49/52 are the counterfactual paths where a *later* `new` throws; the function ends with `delete[] displs; delete[] counts;` @80-81. FP class: GCC analyzer models throwing `operator new[]` as fallible (returns NULL / leaks on the failure branch).
10. **combined iter2 / openai_gpt55__stencil__50…mpi** (10 findings) — identical raw-`new[]` pattern (@36-37 allocs, possible-null @42/43/89, leaks @37/40/74/94). Same throwing-new FP.
11. **static iter2 / openai_gpt55__sparse_la__45…mpi** (9 findings) — `double *localA = new double[…]();` etc. @91-96; possible-null quoting `operator new` @91-96, and by pointer name (`localB` @115, `pivot` @212/218); uninit `*<unknown>` @262 reads `localB[li]` after a fill loop. Same throwing-new/lost-provenance FPs.
12. **static iter2 / gemini_36_flash__scan__30…omp** (6 findings) — all on `#pragma omp parallel for reduction(inscan, +:sum)` @14-15 with `<unknown>` quoted: OMP-outlining artifacts. FP.

**No genuine defect was found in any inspected bucket-c finding.** All are one of three FP families sharing one root cause (the analyzer models allocation as fallible and loses value provenance across allocation/outlining): (c1) `std::vector` element access after construction/resize → terse `NULL '0'`; (c2) raw `new[]` modeled as returning NULL / leaking on counterfactual failure paths; (c3) lost-provenance uninitialized reads (`*<unknown>`, sort/unique iterator internals, OMP outlining).

## 4. Execution probes (Docker, image pareval-thesis, GCC 13.3)

Reproduced the pipeline's reduced-TU analyzer compile (per `tools.py`: system includes of the benchmark's `cpu.cc` [`<algorithm> <cmath> <numeric> <random> <vector>` for all three benchmarks used] + `utilities.hpp` + `generated-code.hpp`; flags from `build_config.py`: `-std=c++17 -O3 [-fopenmp] -DUSE_MPI|USE_OMP -fanalyzer -Wanalyzer-too-complex -c "-DDRIVER_PROBLEM_SIZE=(1<<8)"`, `mpicxx` for mpi / `g++` for omp). Sources copied to scratchpad; repo mounted `:ro`; nothing written to the repo. Exact command pattern:

```
MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/workspace:ro" \
  -v "<scratch>/task5:/scratch" -w /scratch pareval-thesis bash -c \
  'mpicxx -std=c++17 -O3 -DUSE_MPI -I /workspace/drivers/cpp -I /scratch/probe/p1 \
   -fanalyzer -Wanalyzer-too-complex -c "-DDRIVER_PROBLEM_SIZE=(1<<8)" \
   /scratch/probe/p1/reduced.cc -o /scratch/probe/p1/analyzer.o 2> /scratch/probe/p1/stderr.txt'
```

All three probes reproduced the frozen findings exactly (same flags/lines/messages); full stderr = 164KB (P1), 325KB (P2), 123KB (P3) vs. the 8KB stored truncation.

- **P1** (fable stencil50 mpi, bucket-c `NULL '0'` @51): the warning's own 563-line event path contains the tokens on 70 lines and ends: `(76) inlined call to 'std::vector<int>::operator[]' from 'cellsXOR'` → `(77) '0' is NULL`, with the null originating at `this->_M_impl._M_start = this->_M_allocate(__n);` inside `std::_Vector_base::_M_create_storage`. **The terse `NULL '0'` findings are the identical vector-allocation FP; only the one-line message hides it.**
- **P2** (gpt55 scan30 mpi iter2, raw-`new[]` class): the leak/possible-null blocks each end at `'operator new [](…)' leaks here` / the new-expression deref; the four tokens DO appear in the blocks — but only incidentally (e.g. `size_type(this->_M_impl._M_finish - this->_M_impl._M_start)` from an unrelated inlined `vector::size()` on the path). **Whole-block token matching is therefore over-broad**: in this vector-saturated benchmark code nearly any analyzer path traverses vector inlines, so a block-level token filter would also demote genuine findings whose paths merely pass through vector code.
- **P3** (gemini31 hull omp): the two uninit `_M_current` warnings reproduce; their blocks run through `std::sort` internals.

## 5. Deliverable: filter predicate

**The plain 4-token path filter under-catches badly (34.7%) and must be extended. Co-occurrence rules are the wrong extension** — same-sample co-occurrence still misses 222 findings (26.3%), and it blanket-demotes by sample rather than by finding. The message classes themselves are fully separable, so use per-finding message signatures:

```
demote_to_low_confidence(finding) :=
  finding.tool == "gcc_analyzer" AND finding.blocking AND
  finding.check_id IN { -Wanalyzer-null-dereference,
                        -Wanalyzer-possible-null-dereference,
                        -Wanalyzer-use-of-uninitialized-value } AND
  ( T1: message contains any of "_Vector_base","_M_impl","_M_start","_M_finish"
 OR T2: quoted_expr contains "_M_current" OR matches /__\w+\$/ OR starts with "*__"
        # libstdc++ iterator/algorithm internals (__it1$_M_current, *__first.Point::x)
 OR T3: quoted_expr contains "<unknown>"
 OR T4: quoted_expr contains "operator new"     # throwing new modeled as fallible
 OR T5: check_id == -Wanalyzer-null-dereference AND quoted_expr == "0"
        # i.e. message is "dereference of NULL '0'" — proven (P1) to be the same
        # vector-allocation FP with the origin visible only in the event path
  )
  where quoted_expr = text inside the U+2018/U+2019 quotes of message
```

**Coverage (script `predicate.py`; in-scope = the three demotion families, 794 blocking findings):** T1=273, T2=12 (incl. `*__first`), T3=106, T4=15, T5=384; union = **787/794 (99.1%)** demoted, vs. 273 (34.4%) for the plain filter and 622 (73.7% of all 844) for path+co-occurrence. Residue kept blocking (7 findings, all listed): 3× uninit `MEM[(double * const &)&local_… + 8][2305843009213693951]` (deepseek_v4_flash scan30 mpi ×2 runs @37/@42, qwen37_max scan30 mpi @34 — a guarded `local_prefix.back()` after a fill loop, co-located with the 3 `-Wanalyzer-out-of-bounds` "heap-based buffer under-read" findings; FP-shaped but structurally plausible, defensible to keep), 1× uninit `num_threads` (qwen36 scan omp — real benign-race smell), 3× possible-null `localB`/`pivot` (gpt55 sparse45 iter2 — throwing-new FP quoting the pointer name; acceptable residual noise, or catchable by an optional rule "possible-null on a named pointer in a sample that has a T4 finding").

**More precise pipeline-time variant for T5** (the parse step in `tools.py` sees the untruncated stderr): demote a `NULL '0'` finding only if its diagnostic's *final* events name `std::vector`/`std::_Vector_base` members (P1 pattern: `inlined call to 'std::vector<T>::operator[]'` immediately before `'0' is NULL`). Do **not** grep tokens anywhere in the block — P2 shows tokens appear incidentally on unrelated paths, which would make a whole-block filter demote nearly everything.

**False-demotion risk (what the extended predicate would wrongly demote):**
- **T5** is the aggressive rule. Empirically 0/384: every flagged source line was extracted and classified — 383 are subscript expressions (`recvcounts[r] = …`, `displs[0] = 0;`, …), 1 is `receiveCounts.at(process)` — all vector/array element accesses after allocation; 9 samples read in full confirm the FP; P1 proves the mechanism. *In principle* a genuine deref of a constant-propagated nullptr (e.g. `buf = nullptr` on non-root ranks, then `buf[i]`) would produce the same message and be wrongly demoted — none exists in pilot_001, and the event-path-anchored variant eliminates this risk.
- **T3** could mask a genuine uninitialized read whose symbol the analyzer lost; all inspected instances are runtime-initialized vector elements (MPI/loop fills). Demotion ≠ deletion: the finding stays recorded as low_confidence, and dynamic stages (memcheck) still gate genuine cases.
- **T4** would be wrong only for unchecked `new (std::nothrow)`: exactly 1 of the generated sources in all 7 runs uses nothrow (`openai_gpt56_sol__sparse_la__45…mpi`, static iter2), it null-checks all four pointers (lines 83-93), and its record has 0 blocking gcc_analyzer findings → 0 false demotions in pilot data.
- **T2** matches only reserved-identifier internals; model code never names such variables in this dataset.

## 6. Out-of-scope observations

- **malloc-leak (47 blocking, 26 deduped)** is not in the decided demotion scope but is the same allocation-failure modeling: 20 token-bearing (vector-internal storage "leaking" on counterfactual exception paths), 24 `operator new` (later-new-throws paths; the inspected sample `delete[]`s both buffers), 3 `<unknown>`. Flag for a separate demotion decision.
- **out-of-bounds (3)**: all `heap-based buffer under-read` co-located with the residual `MEM[…]` uninit findings on the guarded `.back()` pattern; left blocking.
- Scripts and probe outputs preserved in `C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/task5/` (`buckets.py`, `predicate.py`, `cmsg.py`, `cexpr.py`, `blocks.py`, `events.py`, `residue.py`, `probe/p{1,2,3}/stderr.txt`, `bucket_c.json`, `t5_lines.json`).

> **Adversarial verification: CONFIRMED.** Every load-bearing number matched an independent re-derivation (844/804; buckets 293/209/120/222; iter-0 80 -> 43/14/23; 384 single-message null-derefs, 383 subscripts + 1 .at(); truncation at framework.py:104-105; probe P1's 563-line event path). The only bracketed item — predicate residue 7 vs 8 (coverage 787 vs 786 of 794) — is definition-dependent on the exact T-signature texts and consistent under the natural reading.


---

## Closing table — every headline figure in overview.md, with a quotability verdict

Verdicts: **quotable** (survives as printed) / **quotable with caveat** (correct as computed, but must carry the stated caveat) / **not quotable** (measures an artifact; use the corrected value if one exists).

| overview.md figure | verdict | corrected value / required caveat |
|---|---|---|
| "Statically clean but incorrect" **13.8 % (47/340)** | **not quotable** | **2.7 % (6/225)** on the tool-complete, non-defective-benchmark subset; genuinely-model-caused residue **2.2 % (5/225)** (the 6th is the absolute-epsilon LU artifact). Task 2, §2.2/§2.4. |
| "Statically clean but enhanced-failing" **16.8 % (57/340)** | **not quotable** | **8.9 % (20/225)**; genuinely-model-caused residue **3.6 % (8/225)** (12 of 20 are the convex-hull degenerate-spec artifact). Task 2, §2.2/§2.5. |
| combined_feedback clean-but-incorrect / clean-but-enhanced-failing | **not quotable** (as raw) | **0.0 % (0/220)** (structural: combined stops clean only when tests pass) and **8.2 % (18/220)**, genuine residue **2.3 % (5/220)**. Task 2, §2.3. |
| stencil ParEval pass **3.0 % (1/33)** (all variants) | **not quotable** | Measures the prompt-vs-oracle contradiction (Moore vs von Neumann), not capability. No corrected value exists without re-running against a fixed oracle. |
| stencil enhanced **62.3 % / 62.3 % / 58.9 %** | **not quotable** | Vacuous/discriminator split of the same defect. |
| sparse_la ParEval **21.2 % / 42.4 % / 36.4 %** | **not quotable** | Duplicate-COO oracle inconsistency + NaN false passes; corrected estimate at iter0 with a fixed harness ≈ 64 % (prior audit; not a substitute for a re-run). |
| sparse_la enhanced **88.5 % / 82.1 % / 88.2 %** | **not quotable** | Measured against structurally singular systems with a NaN-blind comparator. |
| ParEval breakdown tables, the other 10 benchmarks | **quotable with caveat** | Caveats: (a) up to 51 final-state passes across variants ride on auto-closed artifacts — quote with the cleaning sensitivity note; (b) reduce/25 mpi "pass" verdicts hide the even-np reduction bug for 4 models (unseeded-rand parity blindness, Task 2 §2.5) — quote reduce/25 mpi pass rates only with that caveat; (c) dense_la/00 contains the one absolute-epsilon rounding artifact (Task 3). |
| Enhanced tests by execution model (275/367/469 + verdict counts) | **quotable with caveat** | As an artifact inventory only; never derive per-execution-model rates (selection-biased pooling — repair share serial 52 % / omp 64 % / mpi 72 %). |
| Enhanced gated totals **386/398/496** | **quotable** | Reproduced cell-for-cell from raw records; gate works as designed. |
| Enhanced serial crash **196** | **not quotable** (as model-bug count) | 100 % = two defensive-throw samples on degenerate sparse specs; the "passing" 9 models passed against a NaN oracle. |
| MPI enhanced timeouts **124** | **quotable with caveat** | All are hard deadlocks from 4 samples (15× empty gap below the wall); not a distribution tail. |
| Blocking-findings-per-tool convergence tables | **quotable with caveat** | compiler: test_feedback iter2 "394" is 2 prose-leak samples — quote distinct-sample counts, not raw finding counts; parcoach/llov "0" cells overstate coverage (e.g. 30/83 errored runs at static iter1); tsan/must columns under static_feedback are not feedback outcomes (excluded from that variant's feedback and stop rule by design). |
| gcc_analyzer blocking counts (181/139/114 etc.) | **not quotable** (as defect counts) | ≥ 99 % of the null-deref / possible-null / uninitialized families match the analyzer FP-class signature (787/794, Task 5); a per-finding message-signature predicate separates them. Quote only after the demotion is applied and counts are re-derived. |
| "Findings per artifact rising" trend (0.46→0.87→1.50) | **not quotable** | Survivor composition (MPI share 33 %→52 %→67 %); per-affected-sample density is flat (2.97→2.62→3.00). |
| Stop-reason distributions | **quotable with caveat** | `stopped_clean` = no blocking **static** findings; 12 of 340 static clean finals carry live dynamic (tsan/must) blocking findings. |
| Race corroboration (omp) table | **quotable with caveat** | Counts verified; the LLOV side is dominated by a known FP on vector-indirection code (5/5 llov-only in the pilot). |
| Runtime cost per tool; generation effort/latency | **quotable** | Dedup verified; no contamination found. |
| Cleaning interventions (8.3 % auto-closed etc.) | **quotable** | And required as the caveat-source for pass rates: 24/33 auto-closed samples pass ParEval at iter0. |
| Data completeness (rows 1903, incomplete 0) | **quotable** | Reconciled exactly; "0 incomplete" verified to mean "no missing records". |
| Correctness-stage tolerance | **quotable with caveat** | Exactly **10/358** validation_failed records are rounding-only (one model × one benchmark, rel ∈ [8.09e-9, 8.22e-9], proven by full re-execution); the [1e-6, 1e-3) band is empty. Not a broad tolerance problem — one surgical case. Task 3. |
| Enhanced-stage tolerance ("do not loosen") | **quotable** | Confirmed for the enhanced stage (0 rounding candidates in 2072 fails); explicitly does **not** transfer to the correctness stage. |
| 60 s enhanced timeout | **quotable with caveat** | Holds for the full run **only if** `dense_la/01_dense_la_solve@4096 extreme_values` is dropped or resized: it fails the *30 s hardcoded baseline gate* (56.3/54.8 s at -O1) and would be silently gated; its model-run replica straddles the 60 s wall (58.6/59.7 s). All other 20 large specs have ≥ 35× headroom. Task 4. |

## Premise corrections (per the "finally" clause)

1. **Task 2's axis-1 reference number "~3.2 %" does not re-derive.** Excluding only the two defective benchmarks gives 8/296 = 2.7 %; the briefed axis-2 counts (74 = 19+25+22+8; 266 complete; 65 combined) verified exactly.
2. **Task 3's briefed receipt overstated the records**: they store only the first 3 mismatches (MISMATCH_REPORT_MAX=3) plus a total — "all 52 rels ≈ 8.1e-9" was undecidable from records and was proven true only by re-execution. The correctness stage has a tolerance problem of exactly one benchmark×model instance, not "at least one" of unknown extent.
3. **Task 4's briefed framing was wrong twice**: (a) 6 of the "21 never-exercised" specs were exercised in the pilot (with matching durations); (b) the spec-killing wall is not the 60 s run timeout but the **hardcoded 30 s baseline gate at -O1** (`baseline_selftest.py:50`), which runs first. Also, 15 of the 21 specs are pattern-inert (no ENHANCED_FILL site) — their pattern/value_range fields are decorative.
4. **Task 5's briefed "path filter" premise is structurally impossible as stated**: the stored findings contain **no path** — only a one-line message (the event path lives in `raw_stderr`, truncated at 8000 chars). A token filter can reach at most 34.7 % (self) / 73.7 % (with co-occurrence). The workable predicate is per-finding message signatures (99.1 % coverage, 7 listed residues, measured false-demotion risk 0 in pilot data), or — better — an event-path-anchored rule at parse time where the untruncated stderr is available.
5. **The implicit premise that surviving clean-but-incorrect cases would be further artifacts is wrong for the majority**: 5 of 6 surviving incorrect samples (and 8 of 20 surviving enhanced failures, static) are genuine model bugs — the design's phenomenon exists; it is just 5× smaller than reported.

## Checked beyond the ask / deliberately skipped

**Beyond the ask:** the reduce/25 even-np reduction-bug class and its ParEval blindness mechanism (unseeded-rand parity with numTries=2 — predicted from first principles, confirmed by executing the frozen binaries); the fft radix-2 oracle's invalidity at non-power-of-two enhanced sizes incl. a silent N=3 case the gate cannot catch and heap corruption at N=5/7 (both are NEW defects, not in the two audits' lists — they belong on the remediation list); the OpenMP task-firstprivate mechanism behind the convex-hull survivor (dedicated Docker probe); full extraction and classification of all 384 `NULL '0'` source lines (Task 5) rather than a sample; timing-scaling siblings establishing that a size-2048 replacement spec for dense_la/01 runs ~5.7 s.

**Deliberately skipped:** no re-runs of pipeline stages and no fixes (Phase-0 ground rules); Task 2's per-sample classification covers the both-clean cell (the thesis number), not all 47/57 (the two defective benchmarks' samples are already classified wholesale by the oracle defects); Task 4 measured serial walls only (the gate is serial by design; MPI startup adds ~0.34 s median, immaterial at the measured magnitudes); malloc-leak and out-of-bounds gcc_analyzer families were characterized but excluded from the predicate (outside the decided demotion scope — flagged for a separate decision).

---

*Produced by Phase 0 (2026-08-22). Analysis scripts and probe outputs are preserved in the session scratchpad (task2/, task3/, task4/, task5/); they are audit artifacts, not part of the repo. Companion document: `thesis/docs/benchmark-example-consistency.md` (Task 1).*
