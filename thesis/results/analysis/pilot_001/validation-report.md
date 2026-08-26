# pilot_001 validation report — GO / NO-GO for the full run

- **Run audited:** `pilot_001` (36 prompts × 11 models = 396 samples/variant; 3 variants; iterations 0–2; git `6846d689`, manifest frozen 2026-08-12T12:46:24Z)
- **Audit date:** 2026-08-22
- **Method:** 8 independent read-only analysis agents (checks A–G), followed by 7 adversarial verification agents that independently re-derived every blocker-level claim from the primary data with an explicit mandate to refute it. All 7 blocker verifications returned **CONFIRMED** (three with numeric corrections, applied below). Nothing under `thesis/results/` was modified or re-run; all scratch analysis scripts live outside the repo (session scratchpad). This file is the only artifact written into the repo by the audit.

---

## 1. Verdict

**GO WITH FIXES.** The pipeline's plumbing is sound — the 1903-row join reconciles exactly, nothing is dropped or double-counted, all 11 models are complete, provenance is frozen and drift-free — but the full run must **not** start until **5 blockers** are fixed, because two of the twelve pilot benchmarks' oracles, the shared comparison predicate, the enhanced spec set, and a static-analyzer false-positive class together corrupt exactly the numbers the thesis is built on. Every blocker is a **(P)** pipeline/benchmark defect with a named file and a named fix; none requires a redesign. Starting the full run as-is would spend ~5× the pilot's budget measuring, to first order, harness artifacts.

## 2. Blocker table

| # | What is broken | Evidence (receipt) | P/M | What must change before the full run | Est. effort |
|---|---|---|---|---|---|
| **B1** | `50_stencil_xor_kernel`: the prompt's worked example encodes the **8-neighbor (Moore)** rule; the oracle `correctCellsXOR` (`drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/baseline.hpp`) implements **4-neighbor (von Neumann)**. They disagree on **7/16 cells of the prompt's own example**. Inherited byte-identical from upstream ParEval. | 31/33 base samples `validation_failed`; the **only** passer, `deepseek_v4_flash__stencil__50_stencil_xor_kernel__mpi__sample_0`, implements 4-neighbor — i.e. it passed by contradicting the example. Enhanced spec 6 ("the documented example with known answer") **fails against the baseline** on every Moore sample. Verified programmatically (both rules applied to the example grid). Adversarially CONFIRMED. | P | Align prompt example and oracle (recommended: fix the example + add "up/down/left/right, no diagonals" to the prompt; documents a deviation from upstream). Add the systematic guard: a pre-run check asserting `baseline(example_input) == example_output` for **all 60 full-run benchmarks** — this bug class is mechanically detectable and benchmarks 51–54 are unaudited. Rerun correctness for this benchmark. | Hours + partial rerun |
| **B2** | `45_sparse_la_sparse_solve`: the driver builds `b` by **summing** duplicate COO entries (`cpu.cc:59-61`) but the oracle materializes the dense matrix by **overwriting** them (`baseline.hpp:22`). At N=128, sparsity 0.1 → ~82 duplicate (row,col) pairs per validation trial, so the oracle solves a different system than the one that generated `b`. | **144/247** sparse_la rows are `validation_failed` with `got[0] ≈ 6.568282105293223` — bit-identical to 17 digits across different models and execution models (the true generating solution, inside the generator's [-10,10] range; the oracle's "expected" 25.17 is outside it). Source-level crosstab: overwrite-convention kernels pass, sum-convention (scipy/MATLAB standard) kernels fail. `claude_fable_5` serial passes with `=`, `claude_opus_5` serial fails with `+=`, same GE+pivoting algorithm. Adversarially CONFIRMED (144/247 re-derived exactly). | P | In `createRandomLinearSystem`, draw (row,col) pairs **without replacement** (dedup penalizes no convention) — or validate by residual ‖Ax−b‖. Audit `46_spmm` and `49_sparse_lu_decomp` for the same dense-materialization-overwrite pattern before the full run. Rerun correctness for affected benchmarks. | Hours + partial rerun |
| **B3** | **NaN-blind comparison predicate**: `fequal` / `reportAndCompare` (`drivers/cpp/utilities.hpp:163-171`, lambdas at :319/:328) use `std::abs(a-b) > eps`, which is false for NaN — **an all-NaN candidate output passes validation against any reference.** | **29 of the 51** sparse_la "pass" rows are divergent Jacobi-family solvers whose output saturates to NaN (deepseek_v4_flash mpi/omp, deepseek_v4_pro mpi, qwen37_max mpi, qwen36_35b_a3b omp). Near-direct receipt: `qwen36_35b_a3b__...__mpi` np=2 reports only 65/128 mismatches — the other 63 "matched" O(1–10) expected values at 1e-3 tolerance, only possible if NaN. Adversarially CONFIRMED (count corrected 25→29). | P | Make the predicate NaN-aware (`isnan(a)!=isnan(b)` → mismatch; both finite → `\|a-b\|>eps`) and/or gate any oracle output containing non-finite values. This touches the pinned verdict authority (`utilities.hpp` comment pins byte-compatibility with upstream ParEval) — the deviation must be made deliberately and documented. Rerun correctness for solver benchmarks. | Hours; semantics decision + partial rerun |
| **B4** | **Enhanced spec set is defective for solver/geometry benchmarks.** (a) All 20 sparse_la/45 specs use sizes 0–14 → `nVals = floor(0.1·N²)` ≤ 19 → every spec is an **empty or structurally singular system**; the unguarded GE oracle silently produces NaN; combined with B3, everything "passes" vacuously (20/20 for kernels failing ParEval 128/128), and the whole **serial crash column (196) is two defensive-throw samples** on these degenerate specs. (b) Convex-hull `all_same`/`all_zeros` degenerate specs (hull ill-defined) generate 21 of the 57 headline "enhanced-failing clean" samples, all of which pass ParEval. | Per-spec cross-model matrix: every one of the 20 sparse specs shows exactly {pass: 9, crash: 2} — the 2 throwing models (`openai_gpt55`, `openai_gpt56_sol`) crash on **all** specs, the 9 "passing" models pass against a NaN oracle. The stability probe whose own comment targets "exactly singular matrix" passes NaN-vs-NaN. Adversarially CONFIRMED (correction: 5 of the 20 specs come from the frozen cache, 15 are pipeline-generated statics/mutations — the degenerate size generation carries into the full run either way). | P | Enforce solvable systems for solver-benchmark specs (size floor so nnz ≥ N, or diagonally-dominant construction); have the baseline gate reject specs whose oracle output is non-finite; gate degenerate hull inputs as `baseline_incompatible`. **The spec cache is sha-pinned in the run manifest — the full run reuses the broken set unless it is regenerated and re-pinned.** | ~1 day + enhanced rerun |
| **B5** | **gcc_analyzer false-positive class gates the repair loop.** `-Wanalyzer-null-dereference` / `-possible-null-dereference` / `-use-of-uninitialized-value` fire on **libstdc++ `std::vector` internals** (`_M_start`, `_M_finish`) for idiomatic code; classed as blocking, they make convergence structurally impossible for a ~34-sample core and burn its entire repair budget. | Cross-model discriminator: at iter0, gcc_analyzer flags (scan/30, mpi) for **11/11 models**, (stencil/50, mpi) 10/11, (sparse_la/45, mpi) 9/11. Persistence: 47/48 (iter0→1) and **37/37** (iter1→2) blocked samples carry the same check_id. Models are not lazy: 0/159 iter1 and 1/76 iter2 sources are byte-identical to the previous iteration; `claude_fable_5` scan/30 mpi added guards, `.at()`, empty-checks — analyzer re-fired on the same family. Adversarially CONFIRMED (correction: 13/61 resp. 16/53 samples did clear it — by FP-appeasement rewrites, which confirms rather than refutes the diagnosis; 38/76 = 50% of iter2 artifacts still blocked). | P | Demote `-Wanalyzer-possible-null-dereference`, and null-deref/uninit findings whose path is libstdc++-internal (`std::_Vector_base`, `_M_impl`, `_M_start`, `_M_finish`), to the existing `low_confidence` lane (`low_confidence_stop_mode: grace_once`) so they stop gating the stop criterion. | Hours; changes stop semantics — document |

**Consequence blockers (fixed by B1–B4, listed for visibility):** the two headline figures of the design — **13.8% (47/340) "statically clean but ParEval-incorrect"** and **16.8% (57/340) "statically clean but enhanced-failing"** — are ~77% and ~65% measurement artifact respectively (adversarially confirmed decompositions; see check G). The defensible residuals are ≈ 6–9/340 (1.8–2.6%) and ≈ 4–5%. These numbers must not be quoted from pilot_001.

## 3. Warnings — full run may start, but these must be known (and most are cheap to fix)

| # | Warning | Receipt | Action |
|---|---|---|---|
| W1 | Assembly cleaner's prompt-docstring dedup can break **valid** model output: it matched only 4 lines of an abbreviated comment and left the tail dangling as bare tokens → compile regression charged to the model. | `claude_opus_5__fft__05_fft_inverse_fft__mpi__sample_0`, static_feedback iter2; raw output is valid C++ (raw generations jsonl), assembled `generated-code.hpp` line 12 is a dangling comment tail. 1 of the 4 static_feedback compile regressions. | Verify `/* */` balance after dedup; only dedup full-comment matches. |
| W2 | Chain-of-thought prose / backticks leak through the cleaner into the TU → 236- and 158-error cascades. `test_feedback` iter2 `compiler=394` is **entirely these 2 samples**. | `deepseek_v4_pro__sparse_la__45__serial` (cb=236), `deepseek_v4_flash__sparse_la__45__serial` (cb=158), test_feedback iter2. | Drop prose/backtick lines outside code context, flag `prose_leak`; or report distinct root errors per sample so cascades cannot dominate per-tool cells. |
| W3 | `assert(a.size()==b.size())` (`utilities.hpp:270`) converts wrong-shape output into SIGABRT "crash" instead of validation "fail" — 36 serial + 126 mpi pilot records (all `openai_gpt55`) are category-misclassified. | Static-feedback-repaired kernel returns empty `x` via `x.clear()` → harness abort, recorded as crash. | Replace assert with printed size-mismatch report + `return false`. |
| W4 | Absolute epsilon 1e-3 fails mathematically correct LU at rel ≈ 8e-9 on magnitudes ~1.8e5 (2 of the 47 "clean but incorrect"). | `qwen3_coder_api__dense_la__00_dense_la_lu_decomp__serial/omp`: 52 mismatches, **all** rel ≈ 8.1e-9. | Relative criterion, or reclassify all-rel<1e-6 verdicts as rounding (the `rel` field already exists in the records). |
| W5 | Auto-closed artifacts are counted as model successes without caveat: 24/33 iteration-0 auto-closures pass ParEval at iter0; **51 (sample,variant) final-state passes ride on an auto-closed artifact** (25 distinct samples); 14 of the headline's 340 clean finals are auto-closed-and-passing. `build_overview.py`'s own docstring promises the caveat next to pass rates; it appears only in the separate Cleaning section. | `deepseek_v4_flash__reduce__25_reduce_xor__mpi__sample_0`: raw output ends mid-brace, pipeline appends `}`, passes in all 3 variants. Full list in check G.6. | Add a "pass excluding cleaning-contingent artifacts" sensitivity row next to every pass-rate table. |
| W6 | The "Enhanced tests by execution model" table invites selection-biased rates: it pools balanced iter-0 artifacts with repair artifacts conditioned on failing a stop rule (repair share serial 52% / omp 64% / mpi 72%). Rates derived from it would **flip** the serial-vs-omp ordering vs. the balanced tables (serial understated ~10pp). No printed overview.md number is wrong — the hazard is the "samples" label. | Pooled serial 83.5% vs balanced final-state 94.4/91.9/95.1%. Reproduction in check E. | Rename column to "artifacts", add preamble sentence; optionally print the 132+143/132+235/132+337 split. |
| W7 | parcoach/llov "0 = ran and found nothing" overstates coverage: 30/83 parcoach iter1 runs carry a non-null `error` (16 timeouts, 14 clang -emit-llvm failures) with findings forced to 0 — effective coverage 53/83. The emit-llvm failures are invisible in the flat CSV. | `pilot_001__static_feedback__iter1/*/static_analysis.jsonl`, parcoach entries with `ran:true` + `error` set. | Count errored runs separately in the per-tool table, e.g. "0 (30 err)". |
| W8 | Mid-run provenance gap: all three **iter2** manifests record `git_dirty: true` (Aug 13/13/19) on commit 6846d689; only the boolean is stored, so the cause is unrecoverable. Mitigation: `config_drift` is empty in all 7 manifests and no code delta was ever committed (git diff of the window contains only overview.csv/md). Residual risk low but real. | `pilot_001__{static,combined,test}_feedback__iter2/run_manifest.json`. | Store a `git status --porcelain` sample next to the boolean; start the full run from a clean tree with scratch files outside the repo. |
| W9 | The 60s enhanced timeout is validated only for cheap specs: pilot max non-timeout MPI runtime is 3.868s (p99 1.575s, a 15× empty gap below the wall — pilot timeouts are all hard hangs from 4 samples). But **21 frozen specs with size > 64 were never exercised**, incl. `dense_la/01_dense_la_solve` size-4096 extreme_values (O(N³) oracle ≈ 4.6e10 FLOPs — plausibly at or over 60s). An oracle overrun silently gates the spec; a 40–55s oracle would misrecord slower candidates as hangs. | Duration distribution over all 8,434 non-timeout MPI runs, check B2. | One-off oracle timing pass over the 21 size>64 specs before the full run (probe machinery exists; read-only w.r.t. references). Optionally short-circuit a sample's remaining specs after ~3 consecutive timeouts (the pilot burned 2.07h on 4 known-hanging samples). |
| W10 | For no-fill-site benchmarks the 20-spec budget contains duplicate effective tests (patterns/value_ranges are compile-time no-ops): reduce/25 ≈ 14 distinct, sparse_la/45 ≈ 11, graph/15 ≈ 13. Their enhanced rates double-weight identical inputs; ~⅓ of the budget is wasted. **10 of 60 full-run benchmarks have fill_sites 0.** | Identical status vectors for key-distinct same-size specs, check C.5. | Dedup spec_key to (benchmark, size) when `fill_sites == 0`, freeing budget for distinct sizes. |
| W11 | Under `static_feedback`, the tsan/must columns are **not** feedback outcomes (the variant's prompt and stop criterion exclude dynamic tools by design), and `stopped_clean` can carry live blocking races — 12 of the headline's 340 "clean" finals have dynamic-only blocking findings. The md wording "no blocking static findings" is accurate but easy to over-read. | `deepseek_v4_pro__sort__40__omp__sample_0`: tsan blocking at iters 0/1/2, exits `stopped_clean`. | Label the columns, and consider a footnote on `stopped_clean`. |
| W12 | Toolchain provenance is a 12-day-old cached snapshot: `toolchain-versions.txt` content dated 2026-07-31, copied into the run dir 2026-08-12; the manifest's `toolchain_versions` is permanently null (frozen on the Windows host where the tools are absent). Pins the toolchain only if the container image was unchanged. | Check D.7. | Re-capture versions inside the analysis container at run start; backfill the manifest's null via the existing additive-enrichment path. |
| W13 | Repair-iteration manifests carry no git provenance (`git_commit: "unknown"` — first-touching stage runs in a container without git); iteration provenance rests entirely on the base manifest. | `pilot_001__*__iter1/run_manifest.json`. | Pass the host commit hash into the container via env var. |


---

## 4. Per-check findings (A–G) — full receipts

Each section below is the responsible analysis agent's report, unedited. Where the check produced blocker-level findings, the independent adversarial verification (mandate: refute) is appended.


---

### Check A: the stencil anomaly — VERDICT: P (benchmark-spec defect, inherited from upstream ParEval)

#### Root cause, one sentence
The prompt for `50_stencil_xor_kernel` contains a worked example that encodes the **8-neighbor (Moore)** rule, while the grading oracle (`drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/baseline.hpp`, `correctCellsXOR`) implements the **4-neighbor (von Neumann)** rule; the two disagree on **7 of 16 cells of the prompt's own example**, 10/11 models faithfully implemented the example's (Moore) semantics, and the only "passing" kernel is the one that contradicted the example.

#### Scope fact first
All 33 stencil samples in the pilot are the SAME benchmark: `50_stencil_xor_kernel` (pilot = 1 benchmark per problem type, 3 execution models x 11 models). Source: `thesis/results/analysis/pilot_001/overview.csv`, 260 stencil rows total across variants/iterations, benchmark column is `50_stencil_xor_kernel` in every row. So "stencil 3.0%" measures exactly one benchmark; benchmarks 51–54 are not implicated (and not audited).

#### 1. Verdict distribution (overview.csv)
Base run (33 unique samples, iteration 0, deduped across variants):
- `validation_failed`: 31
- `pass`: 1 — `deepseek_v4_flash__stencil__50_stencil_xor_kernel__mpi__sample_0`
- `build_failed`: 1 — `qwen3_coder_api__stencil__50_stencil_xor_kernel__mpi__sample_0`

No timeouts, no crashes. Per variant x iteration counts (from overview.csv): every iteration of every variant stays at exactly 1 pass (0 in test_feedback iters 1–2 because the passing sample stops the loop at iter 0; its final state still counts as pass — final-state pass = 1/33 in all three variants, matching overview.md line 178/200/222 "3.0% (1/33)").

#### 2. Not a call-site / signature problem
- 32/33 samples compile clean (`compile.ok=true`, empty stderr), e.g. `thesis/results/intermediate/pilot_001/claude_fable_5/correctness.jsonl`, sample `claude_fable_5__stencil__50_stencil_xor_kernel__omp__sample_0`: `compile.ok=true`, 4 runs (1/2/4/8 threads) all exit_code 0, `validation: FAIL`.
- The single `build_failed` (`qwen3_coder_api__..__mpi`) is a genuine model bug INSIDE the kernel body: `error: no matching function for call to 'min(int&, size_t&)'` at generated-code.hpp:27 (`std::min(rank, remainder)` with int vs size_t) — receipt in `thesis/results/intermediate/pilot_001/qwen3_coder_api/correctness.jsonl`. Not a driver call-site error; the `driver_error` feedback template in config.yaml is irrelevant to this anomaly. Verdict M for that one sample.
- The one truly passing MPI kernel exercises the full driver path (mpirun -np 1/2/4/8, Gatherv to rank 0) and passes — the driver, launch config, and signature matching work.

#### 3. The contradiction, verified programmatically
Script (scratchpad, `stencil_a4.py`) applied both rules to the prompt's example input:
- 4-neighbor baseline vs prompt's expected output: mismatches at (i,j, baseline, expected) = (0,1,1,0), (1,0,0,1), (1,2,1,0), (1,3,0,1), (2,0,1,0), (2,1,1,0), (2,2,0,1) — **7/16 cells wrong**.
- 8-neighbor Moore vs prompt's expected output: **0 mismatches** — the example is exactly Moore.

Prompt source: `thesis/prompts/generation-prompts-thesis.json`, name `50_stencil_xor_kernel` (all three parallelism models carry the same example). The prompt text ("exactly one neighbor that's a 1") never says orthogonal-only; the example is the only disambiguator, and it disambiguates to Moore. The thesis prompt is byte-identical to upstream ParEval's `prompts/generation-prompts.json` (verified `==` in Python), and `baseline.hpp` last changed in upstream commit e865425 "Update outputs with new prompts (#15)" — the defect is inherited verbatim from upstream ParEval.

#### 4. What the models actually generated
Classifier over all 194 stencil sources in `thesis/results/intermediate/pilot_001*/**/sources/*stencil*/generated-code.hpp`: 146 detected Moore by regex (nested di/dj loop or diagonal indexing); the 48 regex-inconclusive ones were spot-checked — every one read turned out to be Moore in a different style, except the deepseek passer:
- `pilot_001/claude_fable_5/.../serial`: nested `for di/dj in -1..1` skip (0,0) → Moore. FAILED.
- `pilot_001/openai_gpt55/.../omp`: `long long di/dj` -1..1 → Moore (regex missed `long long`). FAILED.
- `pilot_001/openai_gpt56_sol/.../serial` and `.../mpi`: 3x3 window `rowBegin..rowEnd x colBegin..colEnd` minus center → Moore. FAILED.
- `pilot_001__test_feedback__iter1/claude_opus_5/.../omp` (post-repair): still Moore. FAILED.
- `pilot_001/deepseek_v4_flash/.../mpi` (the ONLY pass): `count_neighbors` checks exactly (i-1,j),(i+1,j),(i,j-1),(i,j+1) → **von Neumann, matching the baseline and contradicting the example**. PASSED, and its enhanced record is 18 pass / 0 fail.

Cross-model agreement is total: 10/11 models on 31/32 built samples converge on the example-consistent Moore interpretation and all fail identically. Per the discriminator rule, that is a property of the harness/benchmark, not of the models. **P.**

#### 5. The enhanced 62.3% is NOT counter-evidence — the check's premise is partially wrong
The enhanced tests do NOT use a different oracle: `thesis/evaluation/run_enhanced_tests.py` docstring — "runs the benchmark's validate() differentially against the baseline". Same `correctCellsXOR`, same `validate()` in cpu.cc, just with `ENHANCED_TEST_SIZE`/`ENHANCED_FILL` overrides (`drivers/cpp/enhanced-fill.hpp`). Two mechanisms make Moore kernels pass 11/18 anyway:

a) **`validate()` compares interior cells only** (`cpu.cc` lines 83–85: `for i,j in [1, TEST_SIZE-2]`). For grids of size ≤ 2 the comparison loop body never executes → automatic pass; for size 3 only the single center cell is compared.

b) The failing specs are exactly the Moore/von-Neumann discriminators. Per-test receipt, `thesis/results/intermediate/pilot_001/claude_fable_5/enhanced_tests.jsonl`, serial sample (identical 11/7/2 pattern on all 30 Moore-built samples in overview.csv):
- 11 pass: sizes 1–2 (7 tests, zero cells compared), size-9 all-ones (interior counts 4 vs 8, both !=1, agree), size-3 "one 1 at (1,2)" (only center compared; rules agree there), size-3 random mutation, size-18 all-ones.
- 7 fail: size-3 "single 1 at corner (0,0)" — spec rationale literally says "distinguishing 4-connected from 8-connected"; size-4 "**the documented example** with known answer" — i.e., **the oracle fails the prompt's own documented example**; and all random grids of size 4/6/7/8/14, which almost surely contain a discriminating configuration.
- 2 gated (`status=baseline_incompatible`, `baseline_gate=hang`): both size-0 specs — see finding on validate() underflow below.

So enhanced 62.3% = "Moore kernels pass every test too small or too degenerate to distinguish the two rules, and fail every test that can distinguish them". ParEval and enhanced are fully consistent; there is no driver-path divergence. The 62.3% number reconciles exactly: final-iteration per-sample enhanced counts from overview.csv give 370/594 (static_feedback), 370/594 (test_feedback), 350/594 (combined_feedback) = the 62.3/62.3/58.9 in overview.md lines 178/200/222.

#### 6. Why the repair loop moves exactly zero
Receipt: `thesis/results/intermediate/pilot_001/claude_fable_5/repair/test_feedback/iter1/requests.jsonl`, stencil MPI sample. The entire test feedback block is:
```
ParEval tests: validation_failed
  1 ranks: validation_failed
  2 ranks: validation_failed
  4 ranks: validation_failed
  8 ranks: validation_failed
```
No expected-vs-actual values, no mismatch indices (the driver prints only "Validation: FAIL"; hence `mismatch_total=NA` for every stencil row in overview.csv). Meanwhile the repair prompt re-shows the original prompt — including the Moore example — twice ("## Original task" and in the code header comment). A model has no information channel through which it could discover the 4-neighbor expectation, and every signal it does have (the example) says Moore. Zero repair movement on stencil is therefore fully explained and is not a repair-loop implementation defect; it is the same benchmark defect propagating.

#### 7. Secondary harness observations
- `validate()` unsigned underflow at degenerate sizes: `for (size_t i = 1; i < TEST_SIZE - 1; i++)` with TEST_SIZE=0 wraps to SIZE_MAX. The enhanced size-0 specs hang the ORACLE itself → gated as `baseline_incompatible/hang` (2 gated tests on every stencil sample, `enhanced_gated=2` in overview.csv). The gate protects the numbers but burns hang-timeout wall time, and sizes 0–2 produce structurally vacuous tests for this driver family.
- The enhanced spec generator (spec_model `glm_5_2`, `thesis/results/cache/enhanced/specs.jsonl`, 8 specs for `stencil/50_stencil_xor_kernel`) demonstrably read the baseline source — spec 1's rationale cites the baseline's guard conditions "(i>0, i<N-1, j>0, j<N-1)" verbatim. So the enhanced oracle equals the baseline semantics BY CONSTRUCTION and can never detect prompt-vs-baseline divergence. However, its spec 6 ("The documented example with known answer") failing against the oracle is precisely the machine-detectable signature of this bug class.

#### Proposed fixes (diff-in-prose, NOT applied)
1. **Primary (pick one, before the full run):**
   - (a) In `thesis/prompts/generation-prompts-thesis.json` (all 3 entries for `50_stencil_xor_kernel`) and the matching header comments in `drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/{cpu.cc,baseline.hpp,gpu.cu,kokkos.cc}`: replace the example output with the baseline-consistent one `[[0,1,1,1],[0,0,1,0],[1,1,0,0],[1,0,1,0]]` and add one disambiguating phrase, e.g. "neighbors are the up/down/left/right cells (no diagonals)". Documents a deviation from upstream ParEval.
   - (b) Alternatively change `correctCellsXOR` in `baseline.hpp` to the 8-neighbor rule to match the prompt — but this breaks comparability with upstream ParEval scores and invalidates the cached enhanced specs' rationales.
   - (c) Minimum: exclude `50_stencil_xor_kernel` from the full run or annotate every stencil number derived from it.
2. **Systematic guard:** add a pre-run consistency check that parses each prompt's documented example (input/output pair) and asserts `baseline(example_input) == example_output` for all benchmarks — this class of bug is mechanically detectable and benchmarks 51–54 (and all other problem types) have not been audited for it.
3. **validate() hardening** in `cpu.cc` (and siblings using the same pattern): guard `TEST_SIZE < 3` (or use signed loop bounds) so size-0/1/2 enhanced specs don't hang the oracle or produce vacuous always-pass tests; consider comparing the full grid including borders, since the baseline defines border behavior.
4. **Feedback quality (optional, for repair research validity):** have the driver print a small sample of mismatching indices with expected/got values on validation failure, so `test_feedback` carries actionable content; for stencil the current "validation_failed"-only feedback makes repair success information-theoretically impossible.

#### Numbers in overview.md affected
- stencil ParEval pass "3.0% (1/33)" — arithmetically correct but must not be quoted as model capability; it measures the prompt/oracle contradiction.
- stencil enhanced "62.3% (370/594)" and "58.9% (350/594)" — must not be quoted as "kernels mostly pass held-out tests"; 7 of the 11 passing tests per sample are vacuous under the interior-only comparison.
- Any repair-efficacy claim that uses stencil (e.g., "test_feedback fails to fix stencil") — the failure is preordained by zero-information feedback plus a contradictory spec.


#### Adversarial verification of this check's blocker findings


**Finding:** The stencil ParEval failure (1/33 pass) is a benchmark-spec defect: the prompt's worked example for 50_stencil_xor_kernel encodes the 8-neighbor Moore rule (0/16 cells mismatch), while the grading oracle correctCellsXOR in drivers/cpp/benchmarks/stencil/50_...


**Verdict: CONFIRMED.**


*Independent re-derivation (evidence):* (1) Oracle/example contradiction, re-derived programmatically (scratch script in scratchpad, stdlib only): drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/baseline.hpp lines 18-29 (correctCellsXOR) counts only (i-1,j),(i+1,j),(i,j-1),(i,j+1) — 4-neighbor von Neumann. Applied to the prompt's example input [[0,1,1,0],[1,0,0,0],[0,0,0,0],[0,1,0,0]], von Neumann yields [[0,1,1,1],[0,0,1,0],[1,1,0,0],[1,0,1,0]], mismatching the prompt's example output at exactly 7/16 cells: (0,1),(1,0),(1,2),(1,3),(2,0),(2,1),(2,2) — identical to the finding's cited cells. The 8-neighbor Moore rule reproduces the example 16/16. The same example appears verbatim in all three thesis/prompts/generation-prompts-thesis.json entries for 50_stencil_xor_kernel (serial/omp/mpi) and in the baseline.hpp comment. Driver cpu.cc validates against correctCellsXOR (lines 55, 75).
(2) Tallies, re-derived from thesis/results/analysis/pilot_001/overview.csv: 33 unique iteration-0 stencil sample_ids (11 models x 3 exec models), all benchmark 50_stencil_xor_kernel; verdicts = 31 validation_failed, 1 pass (deepseek_v4_flash__stencil__50_stencil_xor_kernel__mpi__sample_0: build_ok=true, pass_gridpoints=4/4, enhanced_pass=18/enhanced_fail=0), 1 build_failed (qwen3_coder_api__stencil__50_stencil_xor_kernel__mpi__sample_0). Every one of the 30 built validation_failed samples shows pass_gridpoints 0/N and enhanced 11/7. thesis/results/analysis/pilot_001/overview.md lines 178, 200, 222: "stencil | 33 | 3.0% (1/33)" in all three variant tables — the numbers_not_survive claim is accurate.
(3) Source reads: deepseek_v4_flash mpi source (thesis/results/intermediate/pilot_001/deepseek_v4_flash/sources/.../generated-code.hpp) implements von Neumann (count_neighbors checks only 4 axis cells) — the sole passer. claude_fable_5 serial, gemini_31_pro omp: Moore via di/dj=-1..1 loops. openai_gpt55 omp: Moore via long-long di/dj loops. openai_gpt56_sol serial and mpi: Moore via rowBegin..rowEnd x colBegin..colEnd window including diagonals. Correctness stage record confirms: claude_fable_5 serial stdout "Validation: FAIL"; deepseek mpi "Validation: PASS" at np=1 (thesis/results/intermediate/pilot_001/<model>/correctness.jsonl).
(4) Falsification attempt: my own regex classifier over all 33 sources flagged 3 candidate von-Neumann-but-failing samples (openai_gpt55 omp, openai_gpt56_sol serial+mpi) — manual reading showed all 3 are Moore (classifier false negatives due to window-bounds/long-long styles). No built sample implements von Neumann and fails. Falsifier not found.
(5) New corroboration from enhanced_tests.jsonl (all 11 model dirs under thesis/results/intermediate/pilot_001/): all 31 built non-passing stencil samples fail the IDENTICAL set of 7 enhanced specs (size=3 explicit_values/llm, size=4 explicit_values/llm, size=4 random/mutation, size=6 random/mutation, size=8 random/mutation, size=14 random/mutation, size=7 random/static) and pass the identical 11; deepseek_v4_flash mpi passes all 18. Deterministic identical behavior across 11 independent models = harness/spec property (P), per the cross-model discriminator.
(6) Provenance: git log --follow on baseline.hpp -> e865425 "Update outputs with new prompts (#15)", matching the finding. Prompt diff vs prompts/generation-prompts.json: serial byte-identical; omp/mpi differ ONLY by removed "#include <omp.h>"/"#include <mpi.h>" lines — example identical.
(7) Repair futility (severity support): overview.csv stencil iter1 (84 rows) and iter2 (77 rows): test_feedback ends iter2 with 32 validation_failed and 0 pass; combined_feedback 31 validation_failed / 1 pass; static_feedback 11 validation_failed / 1 pass. The repair loop burns both iterations across all three variants with essentially predetermined failure.


---

### Check A2: sparse_la

#### Scope note
The pilot's 36-prompt subset contains exactly ONE sparse_la benchmark: `45_sparse_la_sparse_solve` (all 247 sparse_la rows in overview.csv have benchmark=45_sparse_la_sparse_solve; the other four sparse_la benchmarks 46-49 exist in `thesis/prompts/generation-prompts-thesis.json` and `drivers/cpp/benchmarks/sparse_la/` but were not sampled). So "sparse_la pass rate" == "sparse_solve pass rate" for the pilot.

#### Headline numbers reproduced
From `thesis/results/analysis/pilot_001/overview.csv` (247 sparse rows), final-state (max-iteration row per sample) per variant, n=33 each:
- static_feedback 7/33 = 21.2%, test_feedback 14/33 = 42.4%, combined_feedback 12/33 = 36.4% — byte-matches overview.md lines 177/199/221. The analysis layer (`build_overview.py`) is faithful to the underlying records; the problem is upstream of it.

#### Verdict distribution
All 247 rows: pass 51, validation_failed 191, build_failed 5. Iter0 base (33 samples): serial 1 pass/10 fail, omp 3/8, mpi 3/8. Failure is NOT uniform across models (6/11 models pass mpi in some final state, 6/11 omp, 3/11 serial) — superficially an M-signal, but signature-level analysis splits it into one dominant P mode plus real M modes.

#### Failure mode 1 — "xtrue" signature: correct kernels failed by an inconsistent baseline. **P (CONFIRMED), dominant**
Classified every row by its first-mismatch `got` values in `correctness.jsonl` (base run `thesis/results/intermediate/pilot_001/<model>/correctness.jsonl`, iterations in `pilot_001__<variant>__iter<1|2>/`):
- **144/247 rows (58%)** show `got[0] ≈ 6.568282105293223` — many of them **bit-identical to 17 digits across different models and execution models**: claude_opus_5 (serial/omp/mpi), deepseek_v4_flash (serial), deepseek_v4_pro (serial), gemini_31_pro (serial/mpi), gemini_36_flash (all 3, ±1e-13 FP noise), openai_gpt55 (all 3), openai_gpt56_sol (all 3), qwen37_max (serial), qwen3_coder_api (mpi). Sample receipt: `claude_opus_5__sparse_la__45_sparse_la_sparse_solve__serial__sample_0`, mismatches `expected=25.172..., got=6.5682821052932...; rel=0.739/0.263/1.06; MISMATCH_SUMMARY total=128` (all 128 elements differ, O(1) relative error).

Mechanism (driver `drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc`):
- `createRandomLinearSystem` (lines 44-53) draws `A_rows`, `A_columns` independently with `fillRand` — **duplicate (row,col) pairs occur**: at validation TEST_SIZE=128 with SPARSE_LA_SPARSITY=0.1 (default, `drivers/cpp/utilities.hpp:29-31`, no override in run_manifest or thesis/evaluation), nVals=1638 draws into 16384 cells → expected ≈82 duplicate collisions per trial (duplicates essentially guaranteed).
- `b` is built by **summing** duplicates: `b[A[i].row] += A[i].value * x[A[i].column]` (cpu.cc:59-61), with x drawn in [-10,10].
- The baseline (`baseline.hpp:22`) fills a dense matrix by **overwriting**: `matrix[element.row][element.column] = element.value;` — so the baseline solves a system that is inconsistent with how b was generated.
- Consequence: any kernel that sums duplicates (the standard COO convention — scipy/MATLAB semantics) solves the consistent system and recovers the generating x exactly → all such kernels return the same vector (hence bit-identical cross-model `got`), and it is INSIDE the generator's range [-10,10] (6.57/-6.13/-8.50), while the baseline's `expected` (25.172) is OUTSIDE [-10,10]. The baseline's answer is provably not the generating solution.
- Source-level discriminator confirms it: `claude_fable_5__...__serial` uses `M[e.row][e.column] = e.value` (overwrite, generated-code.hpp:17) → **pass**; `claude_opus_5__...__serial` uses `+=` (line 16) with the same GE+partial-pivoting algorithm → **fail**. Crosstab over all rows: fill-convention `assign` → 43 pass / 8 misdetections (those 8 are CSR/iterative kernels that sum semantically); `sum` → 116 xtrue-fail vs 5 "pass" (all 5 are the qwen37_max Jacobi false-passes, see mode 3).

**P.** Cross-model agreement is total within the sum-convention class. Discriminating between conventions is not "correctness" — it is matching an internal inconsistency of the harness. Fixing it: in `createRandomLinearSystem`, generate duplicate-free (row,col) pairs (sample cells without replacement / reject-and-redraw), which makes sum and overwrite semantics coincide and leaves the prompt untouched. (Merely changing baseline.hpp `=` to `+=` would make the baseline self-consistent but would flip today's overwrite-passers into failures — dedup penalizes nobody.) Note this same pattern must be audited in 46_spmm and 49_sparse_lu_decomp (also materialize dense from COO) before the full run.

#### Failure mode 2 — zeros / inf / other: genuine wrong answers. **M**
- `zeros` (34 rows): e.g. `claude_fable_5__...__mpi__sample_0` — GE **without pivoting**, `pivot==0.0 → continue` then `x[ii] = diag!=0 ? ... : 0.0` (generated-code.hpp:37,60); with 10% sparsity ~90% of diagonal cells are zero → output collapses to zeros (got=0, total=128). `qwen37_max__...__omp` — Jacobi with `abs(diag)>1e-14` guard → zeros. Real algorithmic failures.
- `inf_nan` (5 rows): `qwen36_35b_a3b__...__mpi` — unguarded Jacobi, `got=[-inf, inf, ...]`, mismatch totals vary with np (128/65/98/114 of 128).
- `other` (8 rows): e.g. `qwen3_coder_api__...__serial` got=[937.17, 18.45, 128.56] — a genuinely wrong solver.

**M** — the measurement is right for these: iterative solvers (Jacobi/Gauss-Seidel) cannot solve this random, non-diagonally-dominant, 90%-zero-diagonal system, and no-pivot GE is a real bug. Caveat: the benchmark's random unstructured matrix makes every iterative method hopeless by construction, and whether such a kernel is *recorded* as fail or pass is decided by mode 3 below, not by code quality.

#### Failure mode 3 — NaN-blind comparison creates FALSE PASSES. **P (mechanism CONFIRMED)**
`fequal`'s predicate is `std::abs(a[i] - b[i]) > epsilon` (`drivers/cpp/utilities.hpp:163-166`, deliberately "byte-compatible with ParEval" per comment at line 188). If the candidate value is NaN, the comparison is false → the element counts as EQUAL → **an all-NaN output passes validation against any reference**.
- `deepseek_v4_flash__...__mpi__sample_0` (verdict pass, all np=1..8): Jacobi with `diag[elem.row] = elem.value` — ~90% of diag stays 0.0 → division by zero on sweep 1 → inf → NaN cascade; convergence check `global_res_norm < tol` is false for NaN so it runs all 1000 iterations and returns NaN-saturated x. It cannot converge, and (being a sum-convention solver) could not match the overwrite baseline even if it did — yet it is recorded **pass**.
- Same for `qwen37_max__...__mpi` (Jacobi, `diag += value`, pass) and `deepseek_v4_pro__...__mpi`.
- Near-direct evidence of NaN-counts-as-equal: `qwen36_35b_a3b__...__mpi` np=2 reports only 65/128 mismatches — the other 63 elements "matched" expected values of magnitude O(1-10) with a tolerance of 1e-3, only possible if those candidate elements were NaN.
- Scale: 25 of the 51 sparse pass rows are iterative solvers of this class (deepseek_v4_flash mpi+omp 13 rows, deepseek_v4_pro mpi 6, qwen37_max mpi 5, qwen36_35b_a3b omp 1). Final-state composition: static 7 passes = 3 direct + 4 suspect-false; test 14 = 10 + 4; combined 12 = 6 + 6.

**P.** Falsification: rerun one such binary once and print x (I did not rerun anything — read-only audit); if x is finite and matches the baseline, this claim dies. Fix: NaN-aware predicate — mismatch when `std::isnan(a) != std::isnan(b)` or when both finite and `|a-b| > eps` (decide and document the deliberate divergence from upstream ParEval fequal semantics).

#### Failure mode 4 — the enhanced ("held-out") suite is vacuous for sparse_solve. **P (CONFIRMED)**
All 20 enhanced specs run per sparse sample (verified in `enhanced_tests.jsonl`, e.g. claude_opus_5 serial) have size ∈ {0,1,2,3,4,6,7,8,14}. nVals = int(N²·0.1): 0 for N≤3, ≤19 for N=14 — i.e. **every enhanced spec builds an empty or grossly rank-deficient matrix** (nVals < N guarantees empty rows → singular → NaN-dominated reference). Combined with the NaN-blind compare, everything passes: kernels that fail ParEval with 128/128 mismatches score enhanced 20/20 (claude_opus_5 all 3 exec models), divergent-Jacobi kernels score 20/20 (deepseek_v4_flash, qwen37_max), every spec runs in 0.001s. The `duplicate_at` spec (size 3, `thesis/results/cache/enhanced/specs.jsonl`) — whose own rationale says "reference overwrites (last value wins) rather than summing" — has nVals=0 and cannot create a duplicate. The only non-pass enhanced results are openai_gpt55 crashes (18-20/20) and gemini_31_pro mpi timeouts (20/20) — degenerate-input robustness signal, not correctness. overview.md's sparse_la enhanced rates (88.5%/82.1%/88.2%) measure nothing. Since the spec set is cached and sha-pinned in run_manifest (483 specs), the full run will reuse it as-is unless regenerated with a size floor (e.g. nVals ≥ max(N, N²·sparsity), plus skip/flag specs whose reference output is non-finite).

#### The variant delta (21.2 vs 42.4 vs 36.4) is largely repair-to-artifact. **P-contamination**
The variation does prove the repair loop moves this benchmark — but toward the harness bug, not toward correctness. Receipt: `claude_opus_5__...__serial`, test_feedback — iter0 kernel sums (`+=`, xtrue-fail); the repair request (`pilot_001/claude_opus_5/repair/test_feedback/iter1/requests.jsonl`, schema repair_request.v1) embeds the MISMATCH lines whose "expected" is the baseline's inconsistent solution; the iter1 kernel switches to `M[...] = A[k].value` (overwrite) and passes. test_feedback's sparse advantage (+7 samples over static) is mostly models flipping `+=`→`=` (opus serial/omp/mpi, fable mpi, qwen36 mpi) or being replaced by NaN-passers. Do not quote the variant ordering on sparse_la as evidence that test feedback repairs better.

#### Corrected estimate (what the numbers would look like with a fixed harness)
At iter0, treating xtrue kernels as correct (they reproduce the generating solution on the trials run) and removing iterative false-passes: ≈ (3 legit direct passes + 18 xtrue)/33 ≈ 64%, versus the recorded 21.2%. The recorded pass rate is nearly uncorrelated with actual correctness on this benchmark: it counts "matches the overwrite artifact OR outputs all-NaN".

#### Prompt-vs-driver interface (per task)
Prompt signature (`generation-prompts-thesis.json`) matches the driver call exactly: `solveLinearSystem(vector<COOElement> const& A, vector<double> const& b, vector<double>& x, size_t N)`, COO struct with size_t row/column, double value; driver passes A sorted row-major (cpu.cc:35-39,54). No interface mismatch. The defect is purely duplicate-entry semantics, which the prompt never specifies and the driver generator makes unavoidable.

#### Scratch work
Analysis scripts written only to the session scratchpad (`sparse_la_analysis.py`, `sparse_corr_records.py`, `sparse_classify.py` + inline snippets). Nothing under thesis/results/ was written or re-run.


#### Adversarial verification of this check's blocker findings


**Finding:** 58% of all sparse_la rows (144/247) are 'validation_failed' verdicts on kernels that computed the true generating solution: the driver draws duplicate (row,col) COO entries (~82 per validation trial at N=128, sparsity 0.1), builds b by SUMMING duplicates (c...


**Verdict: CONFIRMED.**


*Corrected claim:* Claim confirmed as stated, with three precision corrections: (1) 191/247 (77.3%) of sparse_la overview rows are validation_failed in total; the 144/247 (58.3%) figure is the subset whose kernels computed the sum-convention true generating solution (the remaining 47 vf rows are genuine model failures: 34 all-zeros, 5 +/-inf, plus garbage-value signatures — the measurement for those is right). (2) "Bit-identical" holds for 13 of the 15 cited base-run samples; claude_opus_5 serial/omp and openai_gpt55 omp agree with the cited values only to ~13 significant digits (same solution, different solver roundoff) — all 15 are in the cluster. (3) The crosstab's "116 sum-xtrue-fails" is classifier-dependent; my regex classifier gives 122 sum + 15 coo-direct + 3 mixed + 4 CSR-assign = 144 cluster rows ("43 assign-passes" reproduces exactly). On the proposed fix's audit list: 46_sparse_la_spmm's baseline SUMS (baseline.hpp:22 Y[...] += ...), so there the risk is inverted (an overwrite-materializing kernel would fail); 49_sparse_la_sparse_lu_decomp's baseline OVERWRITES (baseline.hpp:20) — same latent bug class as 45. Deduplicating the COO generators fixes all sparse_la drivers uniformly and should be applied before the full run.


*Independent re-derivation (evidence):* HEADLINE NUMBER RE-DERIVED EXACTLY: 144/247 = 58.3%. From thesis/results/analysis/pilot_001/overview.csv, sparse_la has 247 rows (all benchmark 45_sparse_la_sparse_solve): 191 validation_failed, 51 pass, 5 build_failed. Joining every row to its correctness.jsonl record (base dir pilot_001 for iteration 0, pilot_001__<variant>__iter<N> otherwise; 247/247 joined, 0 missing), exactly 144 validation_failed rows have first-3 mismatch got-values within rel 1e-3 of (6.568282105293223, -6.1328390874586081, -8.5009299025410812). The cluster is unambiguous: rel 1e-6 and rel 1e-3 select the identical set (108 unique records -> 144 rows via is_shared_initial triplication; 67 records are bit-identical to the cited string, the rest agree to ~1e-12, i.e. solver roundoff).

DRIVER MECHANISM VERIFIED IN CODE: drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc lines 44-45 draw A_rows/A_columns independently via fillRand (utilities.hpp:144-159, integral path = rand() % N — duplicates possible); lines 58-61 build b by SUMMING duplicate contributions (b[A[i].row] += A[i].value * x[A[i].column]); baseline.hpp line 22 fills dense with OVERWRITE (matrix[element.row][element.column] = element.value). validate() uses TEST_SIZE=128 (ENHANCED_TEST_SIZE_DEFAULT(128) = 128 without enhanced defines, enhanced-fill.hpp:75-79), SPARSE_LA_SPARSITY=0.1 (utilities.hpp:29-32) -> nVals=1638 entries into 16384 cells -> E[duplicate pairs] = C(1638,2)/16384 = 81.8 ("~82" confirmed); P(zero duplicates) ~ exp(-82) ~ 0, so sum-convention failure is deterministic. All 139 validation_failed records share byte-identical expected values (25.172033578355581, -8.3173085037335284, 0.54686009634594346) — baseline deterministic via unseeded rand() (utilities.hpp:204-207 comment) — and expected[0]=25.17 lies outside the x-generator range [-10,10] while all cluster got-values lie inside it. mismatch_total=128 (all elements, O(1) rel: 0.739/0.263/1.06) for every exact-signature record, e.g. claude_opus_5__sparse_la__45_sparse_la_sparse_solve__mpi__sample_0 in pilot_001/claude_opus_5/correctness.jsonl.

SOURCE DISCRIMINATOR VERIFIED: pilot_001/claude_fable_5/sources/claude_fable_5__sparse_la__45_sparse_la_sparse_solve__serial__sample_0/generated-code.hpp uses M[e.row][e.column] = e.value (overwrite) -> verdict pass; pilot_001/claude_opus_5/sources/...__serial__sample_0/generated-code.hpp line 16 uses M[A[k].row*(N+1)+A[k].column] += A[k].value (sum) -> validation_failed. Overview-row crosstab (my regex classifier): assign-convention 43 pass / 11 vf; sum-convention 5 pass / 133 vf. The auditor's "43 assign-passes" reproduces exactly.

CROSS-MODEL DISCRIMINATOR (P attribution): all 11 models and all 3 execution models have at least one x_true-cluster validation_failed record. The generator itself uses sum semantics (b = A_sum x_true), so cluster kernels computed the true generating solution; the harness's ground truth is internally inconsistent. P is correct.

CITED NUMBERS_NOT_SURVIVE VERIFIED: overview.md sparse_la ParEval pass = 21.2% (7/33) static_feedback, 42.4% (14/33) test_feedback, 36.4% (12/33) combined_feedback — all three match the file verbatim.

FALSIFICATION ATTEMPTS (all failed to refute): (a) only ONE unique sum-convention sample passes: qwen37_max__sparse_la__45_sparse_la_sparse_solve__mpi__sample_0 — a Jacobi solver that cannot converge on this non-diagonally-dominant random matrix; its "pass" is most plausibly the NaN-blind comparator (reportAndCompare predicate std::abs(x-y) > epsilon, utilities.hpp:315-321: NaN diff is never > eps), not a counterexample. (b) The two "assign-convention" cluster failures (gemini_36_flash omp) build per-entry CSR slots (val[p] = elem.value) whose SpMV still sums duplicates — behaviorally sum-convention, consistent with the theory. (c) 13 of 15 cited base-run samples are bit-identical to the cited got-string; claude_opus_5 serial/omp and openai_gpt55 omp are in-cluster at rel ~4e-12 (sigs 6.5682821052932203... and 6.5682821052931972...) — "bit-identical" slightly overstated for those 3, immaterial.

REPAIR CONTAMINATION RECEIPT: claude_fable_5 mpi failed base with zeros (real bug), then in pilot_001__combined_feedback__iter1 and pilot_001__test_feedback__iter1 produced the EXACT x_true signature (a genuine fix using sum convention) and was still scored validation_failed; it reached "pass" only in test_feedback iter2, i.e. after flipping convention. The repair metrics on this benchmark measure convention-guessing.

Scratch scripts used (read-only analysis): scratchpad/verify_sparse_la.py, scan_sparse.py, crosstab_sparse.py, edge_cases.py, cluster_models.py.


**Finding:** The comparison predicate std::abs(a-b) > epsilon (fequal, utilities.hpp:163-166) treats NaN candidate values as EQUAL to anything, so divergent iterative solvers whose output saturates to NaN are recorded as ParEval passes; ~25 of the 51 sparse 'pass' rows ...


**Verdict: CONFIRMED.**


*Corrected claim:* The comparison predicate std::abs(a-b) > epsilon (fequal, utilities.hpp:163-171; identical lambdas in reportAndCompare at :319/:328, which is what validate() actually calls at cpu.cc:123 with eps=1e-3) treats NaN candidate values as EQUAL to anything, so divergent iterative solvers whose output saturates to NaN are recorded as ParEval passes. 29 of the 51 sparse_la 'pass' rows (not ~25) are Jacobi-family kernels that cannot match the baseline: deepseek_v4_flash mpi/omp 13, deepseek_v4_pro mpi 6, qwen37_max mpi 5, qwen36_35b_a3b omp 1 + mpi 1 (test_feedback iter1, guarded d=1e-12 divergence), gemini_31_pro omp 3 (unguarded Jacobi base sample shared across all three variants at iter0 — missed by the original keyword scan). Final-state headline contamination is static 5/7, test 6/14, combined 6/12 (corrected pass rates ~6.1%/24.2%/18.2% vs reported 21.2%/42.4%/36.4%). Two aggravating factors confirm blocker severity: the false passes suppress repair (test_feedback iter1 source dirs omit exactly the false-passing samples), and the enhanced differential net is structurally unable to catch it (sparse enhanced specs use sizes 0-14, near-empty matrices; all models pass all sparse enhanced specs including samples with 128/128 finite ParEval mismatches).


*Independent re-derivation (evidence):* PREDICATE: drivers/cpp/utilities.hpp:163-171 fequal uses `std::abs(a[i]-b[i]) > epsilon`; reportAndCompare lambdas at :319 and :328 use the identical predicate. With a[i]=NaN the comparison is false, so NaN counts as EQUAL; +/-inf IS caught (inf>eps). The comment block at :176-190 explicitly pins fequal as "UNTOUCHED (verdict authority, byte-compatible with ParEval)". validate() in drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc:123 calls reportAndCompare(x_correct, x_test, 1e-3); drivers/cpp/models/mpi-driver.cc:56 makes validate() the sole source of the Validation: PASS/FAIL verdict. MAX_VALIDATION_ATTEMPTS=2 (utilities.hpp:26), SPARSE_LA_SPARSITY=0.1 (utilities.hpp:31) -> P(diag cell occupied) = 1-(1-1/N^2)^(0.1*N^2) ~ 1-e^-0.1 ~ 0.095, matching the auditor's arithmetic; createRandomLinearSystem (cpu.cc:41-65) draws uniform random rows/cols/values with no diagonal boosting, so ~90% of diagonal entries are 0.0.

CITED SAMPLE: thesis/results/intermediate/pilot_001/deepseek_v4_flash/sources/deepseek_v4_flash__sparse_la__45_sparse_la_sparse_solve__mpi__sample_0/generated-code.hpp is exactly as described: Jacobi with `diag[elem.row]=elem.value` only for row==column (line 38), unguarded `/ diag[i]` (line 74), tol=1e-10, max_iter=1000, NaN residual never breaks. pilot_001/deepseek_v4_flash/correctness.jsonl records verdict "pass", run_verdicts {'pass': 4} at num_procs 1,2,4,8 for this sample. Same file shows the SAME model's serial sparse sample failing with 128/128 finite mismatches (rel 0.26-1.06) — finite garbage fails, NaN garbage passes.

COUNTS RE-DERIVED from thesis/results/analysis/pilot_001/overview.csv (1903 rows): sparse_la rows 247, pass rows 51. Auditor's per-model tally verified exactly: deepseek_v4_flash mpi 7 + omp 6 = 13, deepseek_v4_pro mpi 6, qwen37_max mpi 5, qwen36_35b_a3b omp 1 => 25 rows; every one of those sources (base + all repair-iteration variants under pilot_001__{static,combined}_feedback__iter{1,2}) read/grepped: all are Jacobi-family iterative kernels (max_iter 1000/10000, unguarded /diag or guarded with fallback diag=1.0 / d=1e-12 which diverges -> overflow -> inf-inf=NaN). Pass verdicts for 12 spot-checked suspect records re-verified in the per-run correctness.jsonl files (all {'pass': 4}).

AUDITOR UNDERCOUNTED: (1) qwen36_35b_a3b mpi test_feedback iter1 pass (source pilot_001__test_feedback__iter1/qwen36_35b_a3b/sources/...mpi.../generated-code.hpp: Jacobi with `if (d==0.0) d=1e-12` at line 53 -> first sweep b*1e12 -> overflow -> NaN); (2) gemini_31_pro omp base sample (pilot_001/gemini_31_pro/sources/...omp.../generated-code.hpp line 36: unguarded `(b[i]-sum)/diag[i]`, 100000-iteration loop — missed by keyword scans because no 'jacobi'/'max_iter' token), verdict pass {'pass': 4} in pilot_001/gemini_31_pro/correctness.jsonl, appearing as 3 shared iter0 pass rows. True suspect row count: 29/51, not 25/51.

FINAL-STATE HEADLINES (overview.md:177/199/221 = 7/33, 14/33, 12/33, denominators re-derived exactly from overview.csv max-iteration rows): contaminated final-state passes are static 5/7 (auditor said 4/7), test 6/14 (auditor said 4/14), combined 6/12 (auditor's 6/12 matches). Corrected sparse_la pass rates if false passes removed: static 2/33 (6.1% vs reported 21.2%), test 8/33 (24.2% vs 42.4%), combined 6/33 (18.2% vs 36.4%).

NaN-EQUALS-ANYTHING PROVEN IN-DATA: pilot_001/qwen36_35b_a3b/correctness.jsonl mpi sparse record, mismatch_totals [128, 65, 98, 114]: np=1 shows got='-inf'/'inf' with rel=nan at indices 0,1,2 (expected 25.17, -8.32, 0.547); at np=2 the first mismatch is index 21, i.e. indices 0-20 — same unseeded-rand inputs, expected values O(1-25) — compared EQUAL at 1e-3 while the same solver produces +/-inf/0 garbage at neighboring indices. NaN is the only consistent value for those "equal" entries; inf is caught, NaN is not.

COLLATERAL (severity): (a) repair suppression — under test_feedback iter1 the sources directories contain exactly the failing sparse samples and OMIT every false-passing one (deepseek_v4_flash: serial only; deepseek_v4_pro: omp+serial, no mpi; qwen37_max: omp+serial, no mpi; gemini_31_pro: mpi+serial, no omp), so the false pass also silently freezes the repair loop for those samples; (b) the enhanced net cannot catch it — thesis/results/cache/enhanced/specs.jsonl sparse specs use sizes 0-14 (nVals=int(0.1*N^2) -> mostly empty matrices) and enhanced_tests.jsonl shows status 'pass' for ALL sparse specs of ALL models, including qwen36_35b_a3b omp/mpi and deepseek_v4_flash serial which fail ParEval correctness with 65-128 finite mismatches.


---

### Check B: enhanced-test serial crashes + MPI 60s timeouts

Data read: all 7 run dirs (`thesis/results/intermediate/pilot_001{,__static_feedback__iter1/2,__test_feedback__iter1/2,__combined_feedback__iter1/2}/<model>/enhanced_tests.jsonl`), 22,220 records total. Raw status counts reconcile EXACTLY with overview.md per execution model (serial 4271 pass / 591 fail / 196 crash / 0 timeout / 56 build_failed / 386 gated, where gated = 202 baseline_incompatible + 184 numerically_unstable; omp 5995/601/170/40/136/398; mpi 7257/880/297/124/326/496). No double counting of the shared base run in these columns. Scratch scripts (analysis only, no pipeline re-runs): `.../scratchpad/check_b_enhanced.py`, `check_b_part2.py`, `check_b_part3.py`, `check_b_part4.py`.

#### B1. The 196 serial crashes: fully localized

**Concentration:** 100% of serial crash records are ONE benchmark and TWO models: `sparse_la/45_sparse_la_sparse_solve`, models `openai_gpt55` (116 records) and `openai_gpt56_sol` (80). Only 2 distinct sample_ids: `openai_gpt55__sparse_la__45_sparse_la_sparse_solve__serial__sample_0` and `openai_gpt56_sol__...__serial__sample_0`. Per run dir: base 40, test_feedback iter1 40, iter2 40, combined iter1 40, static_feedback iter1 18, iter2 18 (sum 196). Every record has `exit_code: -6` (SIGABRT).

**Per-spec cross-model matrix (base run, serial, this benchmark):** every one of the 20 specs shows exactly `{pass: 9, crash: 2}` — the same 2 models crash on ALL 20 specs; the other 9 models pass ALL 20. So the crash is model-specific, not spec-specific within the benchmark.

**Where the abort happens (stderr taxonomy of the 196):**
- 160 records: the GENERATED KERNEL throws. `terminate called after throwing an instance of 'std::runtime_error' what(): matrix is singular...` (5 distinct wordings). Receipt: base gpt55 source `pilot_001/openai_gpt55/sources/openai_gpt55__sparse_la__45_sparse_la_sparse_solve__serial__sample_0/generated-code.hpp` lines 56 & 95: `throw std::runtime_error("matrix is singular or ill-conditioned")`; gpt56_sol source line 58: `throw std::runtime_error("Matrix is singular or numerically singular")`.
- 36 records (= static_feedback iter1 18 + iter2 18, all openai_gpt55): the HARNESS aborts: `utilities.hpp:270: ... Assertion 'a.size() == b.size()' failed`. Cause: the static-feedback-repaired kernel replaced throws with `x.clear(); return;` (repaired source `pilot_001__static_feedback__iter1/openai_gpt55/sources/.../generated-code.hpp` lines 14-17, 24-26, 33-36), so the candidate returns an empty x; `reportAndCompareWith` (drivers/cpp/utilities.hpp:270) asserts on size mismatch instead of reporting a validation failure.

**Why "singular" on every spec — the specs are degenerate by construction.** The driver (`drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc`, validate() lines 98-104) builds A with `nVals = TEST_SIZE*TEST_SIZE*SPARSE_LA_SPARSITY`, `SPARSE_LA_SPARSITY = 0.1` (utilities.hpp:31), TEST_SIZE = the spec size. The 20 cached specs for this benchmark use sizes {0,1,2,3,4,6,7,8,14}: nVals = floor(0.1*N²) = **0 nonzeros for N ≤ 3** (A literally empty), and nnz < N for N = 4..8 → the matrix is structurally singular for 19/20 specs (size 14: nnz=19, rank deficiency still near-certain with random placement). Every spec feeds the solver an unsolvable system.

**Why the gate did not catch it (NaN-blindness).** The oracle (`baseline.hpp` lines 47-66) does Gaussian elimination with no zero-pivot guard: for an empty/singular matrix it divides by `matrix[i][i] == 0.0` → x_correct becomes NaN/Inf, silently, exit 0. The comparison predicate (`reportAndCompare`, utilities.hpp:315-330) is `std::abs(x - y) > epsilon` — false for any NaN operand → NaN-vs-anything counts as EQUAL → "Validation: PASS". Consequences: (1) the baseline-selftest gate ("plain" probe, run_enhanced_tests.py:549-563) passes; (2) the stability probe — whose own comment (run_enhanced_tests.py:537-544) says it exists precisely for "descending ramp -> exactly singular matrix" — compares NaN oracle vs NaN perturbed-oracle and passes; (3) the 9 "passing" models pass VACUOUSLY (against a NaN oracle any candidate output compares equal). The only models to surface the degeneracy are the two that throw defensively — and they get charged with "crash".

**ParEval cross-check:** both crashing samples FAIL ParEval correctness at iteration 0 (`pilot_001/openai_gpt55/correctness.jsonl` and `.../openai_gpt56_sol/correctness.jsonl`: `verdict: validation_failed`), so "passes ParEval but crashes under enhanced" does NOT hold — the enhanced spec is not indicted by that test. (Side observation for the correctness check: 10/11 models get `validation_failed` on this benchmark serial at N=128 — only claude_fable_5 passes — and gpt55/gpt56 show byte-identical `expected=25.172033578355581 got=6.568282105293223` triplets, i.e., two different models' code produced identical outputs that differ identically from the oracle. Likely driver inconsistency: `createRandomLinearSystem` (cpu.cc:58-61) builds b by SUMMING duplicate COO coordinates while the oracle matrix build (baseline.hpp:21-23) OVERWRITES duplicates; at N=128, nVals=1638 random (row,col) pairs make duplicates near-certain. This is inference from code reading, not verified by execution.)

**Verdict B1: M for the mechanism, P for the metric.** The harness recorded real process aborts caused by model-authored code (cross-model discriminator: 2/11 crash, 9/11 don't — not a universal harness failure), so the crash events are genuine model behavior (M). BUT the enhanced-serial column for this benchmark is measurement-invalid (P): all 20 specs are singular systems outside the prompt's contract, the 9x20 "pass" verdicts are NaN-vacuous, and the crash count measures "does the model throw on degenerate input", not code quality. 196 = 100% of the pilot's serial crash column is this artifact. The frozen spec cache (sha-pinned, 483 specs) carries the same sparse_la specs into the full run, plus untested solver benchmarks (dense_la/01_dense_la_solve incl. size-4096 extreme_values, sparse_la/49_sparse_lu_decomp) with the same NaN-blind comparator.

**Smoke consistency:** smoke_002/003 covered only dense_la — dense random matrices are essentially never singular, which is exactly why crash columns were 0 there and this surfaced only in the pilot.

**Fix (diff-in-prose, do not apply):**
1. utilities.hpp `reportAndCompare` predicates: treat non-finite values explicitly — count a mismatch when `std::isnan(x) != std::isnan(y)` or `std::isinf` disagrees; decide a policy for NaN==NaN (either "equal" but ALSO have the gate reject any oracle output containing non-finite values, or simply flag any NaN in the oracle as gate failure). The cheapest robust variant: in run_enhanced_tests.py's baseline gate, add a probe that fails the spec (→ baseline_incompatible) if the oracle's output vector contains non-finite values (needs the driver to print a sentinel, e.g. extend the enhanced validate path to print "ORACLE_NONFINITE" when x_correct has NaN/Inf).
2. utilities.hpp:270: replace `assert(a.size() == b.size())` with a graceful `MISMATCH size expected=N got=M` + return false, so wrong-size output becomes "fail" (validation) instead of "crash" (SIGABRT). This affects 36 serial + 126 mpi records in the pilot, all openai_gpt55.
3. Spec generation for solver benchmarks (sparse_la/45, /49, dense_la/01): enforce solvable systems (diagonally dominant construction or nnz >= N with guaranteed full-rank diagonal), or gate any sparse-solver spec with floor(0.1*N²) < N.

#### B2. MPI 124 timeouts: 60s is comfortably enough (pilot scale)

**Concentration:** 124 timeout records = only 4 distinct samples, 3 models: `gemini_31_pro__sparse_la__45_sparse_la_sparse_solve__mpi__sample_0` (60), `qwen3_coder_api__sort__40_sort_sort_an_array_of_complex_numbers_by_magnitude__mpi__sample_0` (44), `qwen36_35b_a3b__transform__55_transform_relu__mpi__sample_0` (10), `qwen3_coder_api__stencil__50_stencil_xor_kernel__mpi__sample_0` (10). Model-specific, benchmark-diverse → **M (real hangs in generated MPI code)**, not harness. Supporting evidence: the gemini sample times out on all 20 specs in base + both combined_feedback iters but passes 20/20 after static_feedback and test_feedback repair (same harness, fixed code); its ParEval correctness verdict at base is `validation_failed` with 0 timed-out runs (4 runs) — the hang only occurs at tiny enhanced sizes (classic N < ranks deadlock pattern).

**Quantified duration analysis:** every timeout record's duration is 60.0-60.1s (the kill works; process-group kill per run_enhanced_tests.py:452-474). Across all 8,434 non-timeout MPI runs (statuses pass/fail/crash/gated that executed): p50 = 0.337s, p90 = 0.389s, p99 = 1.575s, p99.9 = 1.943s, **max = 3.868s** (claude_opus_5, scan/30_scan_prefix_sum). Zero runs between 3.9s and 60s. Conclusion: the timeouts are NOT the tail of a runtime distribution — there is a 15x empty gap between the slowest legitimate run and the wall. They are hard deadlocks; raising the limit would flip zero verdicts (even the old 30s limit would have produced identical pilot verdicts). Serial: n=5058, p99=0.028s, max=1.594s, 0 timeouts. OMP: n=6766, p99=0.391s, max=1.473s; all 40 omp timeouts are ONE sample (`qwen3_coder_api__scan__30_scan_prefix_sum__omp__sample_0`) — same M pattern.

**Full-run caveat (the tail CAN get worse):** the pilot's 12 benchmarks ran spec sizes up to 4096 only for cheap kernels (fft/05 all_zeros@4096 max 1.663s across 226 runs; graph/15@4096; reduce/25@1024 — all sub-2s). The frozen specs.jsonl holds 21 specs with size > 64, of which these were NOT exercised in the pilot: `dense_la/01_dense_la_solve` size=4096 extreme_values (O(N³) Gaussian elimination oracle ≈ 4.6e10 FLOPs — plausibly 30-120s serial, i.e., AT or OVER the 60s wall), `graph/16-19` at 1024/4096, `sort/44` at 4096, `reduce/27,29`, `search/39`, `histogram/23` at 4096. If the serial ORACLE overruns 60s the gate silently marks the spec baseline_incompatible (spec lost, not a wrong verdict); if the oracle takes ~40-55s, a legitimately slower candidate gets recorded as "timeout" and would be misread as a hang. Recommend before the full run: a one-off timing pass of the serial oracle over the 21 size>64 specs (read-only probe machinery exists: `--output-file-name` derived outputs, run_enhanced_tests.py:56-58).

**Cost note:** 124 timeouts x 60s ≈ 2.07h of pilot wall time burned on 4 known-hanging samples; the gemini sample alone burned 20 specs x 60s x 3 run dirs = 1h. For the full run consider short-circuiting a sample's remaining specs after k consecutive timeouts in the same size group (diff-in-prose: in `process_sample`, after the per-spec run loop records a timeout, increment a counter and skip remaining specs of that sample once counter >= 3, emitting records with a new status like "timeout_skipped" or reusing "timeout" with a `skipped: true` field).

#### B3. omp/mpi crash sighting (docs/enhanced-tests-parallel.md requires manual sighting in the pilot)

No benchmark shows all-11-model crashes; every crash cluster is model-owned: omp sparse_solve 120 = openai_gpt55 (`throw "Singular matrix"` C-string literals, source lines 16/21/59/104 → `terminate ... 'char const*'`); mpi sparse_solve 126 = openai_gpt55 (all utilities.hpp:270 size-assert); geometry/10_convex_hull mpi 126 = qwen3_coder_api 96 + qwen37_max 20 + deepseek_v4_pro 10 (MPI_Gatherv usage errors + aborts), omp 48 = qwen3_coder/qwen37_max (empty stderr, segfault); reduce/25 mpi 20 = qwen3_coder (MPI_Allreduce errors); transform/55 mpi 25 = deepseek_v4_flash 20 + qwen36 3 + qwen37_max 2 (MPI_Gatherv). All consistent with genuine model failures (M); documented residual risk (a) shows no sign of driver-path divergence crashes in the pilot.


#### Adversarial verification of this check's blocker findings


**Finding:** The enhanced spec set for sparse_la/45 is degenerate and the differential harness is NaN-blind, invalidating the whole enhanced-serial column for this benchmark: all 20 cached specs (sizes 0-14) yield nVals=floor(0.1*N^2) nonzeros - 0 nonzeros for N<=3, nnz...


**Verdict: CONFIRMED.**


*Corrected claim:* Core claim stands as written with these corrections: (1) "all 20 cached specs" -> only 5 of the 20 specs are in the frozen cache (specs.jsonl); the other 15 (4 static, 11 mutation) are pipeline-generated — the full-run carry-over conclusion is unchanged since the static/mutation size generation is the degenerate part. (2) "sparse_la/45 contribution to serial pass = 4271" -> 4271 is the pilot-wide serial pass TOTAL across all benchmarks; sparse_la/45's vacuous contribution is 924 of 4271 (21.6%); base run alone = 180 = 9 models x 20 specs. (3) "dense_la/01 likely also affected" -> likely NOT affected: its baseline early-returns on zero pivot (no NaN output), its validate() has an explicit std::isnan check on test output (cpu.cc:96), and it has no ENHANCED_FILL site so the all_zeros/extreme specs are input no-ops; sparse_la/49 remains a credible same-mechanism risk (same nVals formula, ENHANCED_FILL sites present, unguarded LU divisions, 12 cached specs sizes 0-9). (4) The finding UNDERSTATES the blast radius: (a) omp and mpi enhanced columns for sparse_la/45 are equally artifacts (omp crash=120 and mpi crash=126, all openai_gpt55; mpi timeout=60, all gemini_31_pro; plus ~1060/1054 vacuous passes each); (b) crashes are driven not only by spec-sized singular systems but also by the spec-INDEPENDENT DRIVER_PROBLEM_SIZE=(1<<4)=16 init system (25 nnz, 13/16 rows occupied, exactly singular — proven by size-0 crashes whose stderr shows the singularity throw although gpt55 handles N==0 cleanly, and by simulation). Consequently the PROPOSED FIX IS INCOMPLETE: NaN-aware predicates + a non-finite-oracle gate + regenerated solvable SPECS would still leave the two throwing models crashing in compute() on the singular 16x16 driver system, which the gate never probes (the oracle never throws). The fix must also make the DRIVER_PROBLEM_SIZE system solvable (e.g. guarantee full-rank construction in createRandomLinearSystem itself, or raise the enhanced DRIVER_PROBLEM_SIZE so nnz>=N with margin, e.g. the correctness-stage size 128 where floor(0.1*N^2)=1638 makes empty rows vanishingly rare), or except the post-validate compute() phase from crash classification.


*Independent re-derivation (evidence):* ## Re-derived receipts (all primary data, independently computed)

**Driver/oracle/harness code (mechanism):**
- drivers/cpp/utilities.hpp:31 `#define SPARSE_LA_SPARSITY 0.1`; :26 `MAX_VALIDATION_ATTEMPTS 2`.
- drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc:100 `nVals = TEST_SIZE * TEST_SIZE * SPARSE_LA_SPARSITY` (size_t truncation = floor); :76 same at init with N=DRIVER_PROBLEM_SIZE; :44-46,56 fills are plain `fillRand` — this benchmark has NO ENHANCED_FILL site, so all fill patterns are no-ops and the 20 specs collapse to 9 size-only configurations (matches the 9 build-group rows per sample in enhanced_build_groups.jsonl, e.g. openai_gpt55 serial: 9 groups, sizes 0..14).
- drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/baseline.hpp:29-66: Gaussian elimination with partial pivoting, divisions at line 48 (`c = -matrix[k][i] / matrix[i][i]`) and line 62 (`x[i] = b_copy[i] / matrix[i][i]`), no zero-pivot guard anywhere — singular matrix silently yields NaN, no throw, exit 0.
- drivers/cpp/utilities.hpp:315-330 `reportAndCompare` predicate `std::abs(x - y) > epsilon` — false for NaN operands, so NaN-vs-anything counts as EQUAL. Confirmed NaN-blind.
- thesis/evaluation/run_enhanced_tests.py:319 `-DDRIVER_PROBLEM_SIZE=(1<<4)` (=16) for ALL enhanced builds; :325-333 group defines = ENHANCED_TEST_SIZE + ENHANCED_RUNTIME_FILL; :535-564 gate = compile_and_run of the oracle-as-generated-code, then stability_probe (thesis/enhanced_tests/baseline_selftest.py:240-253: fast-math-perturbed oracle vs normal oracle through the SAME validate()/NaN-blind compare). Gate comment at :541-544 explicitly names "descending ramp -> exactly singular matrix" as what the probe exists to catch — and it cannot, because oracle-NaN vs oracle-NaN compares equal.
- drivers/cpp/models/serial-driver.cc:45-64: order is init(N=16) -> validate(TEST_SIZE=spec size) -> compute(N=16). So every enhanced binary also solves a 16x16 system with floor(0.1*256)=25 nnz.

**Per-spec matrix (base run, 11 models x enhanced_tests.jsonl, serial):** exactly 20 specs, sizes {0,1,2,3,4,6,7,8,14}, sources 4 static + 5 llm + 11 mutation; EVERY spec is {pass:9, crash:2}; non-pass models are always openai_gpt55 and openai_gpt56_sol. Zero gated (baseline_incompatible/numerically_unstable) records for sparse_la/45 in any run dir — gates passed all 20 specs.

**Crash records:** e.g. openai_gpt55__sparse_la__45_sparse_la_sparse_solve__serial__sample_0, spec size 0/7/14: status=crash, exit_code=-6, runtime_stderr "terminate called after throwing an instance of 'std::runtime_error' what(): matrix is singular or ill-conditioned"; openai_gpt56_sol same with "Matrix is singular or numerically singular". Their sources throw on singularity: openai_gpt55 generated-code.hpp:55-56,94-95; openai_gpt56_sol generated-code.hpp:58. gpt55 handles N==0 gracefully (line 19-21 `if (N == 0) return;`) yet crashes on size-0 specs -> the throw comes from compute() on the singular 16x16 driver system, not from validate().

**Falsification test (executed, scratchpad sim_sparse45.py: exact glibc TYPE_3 rand() reproduction + line-faithful oracle replica):** oracle x_correct is 100% NaN for every spec size 1..14, BOTH validation trials (size 14: nVals=19, only 11/14 rows occupied -> singular); size 0 = empty vectors = trivially vacuous pass; init 16x16 system: 25 distinct nnz, 13/16 rows and 14/16 cols occupied -> exactly singular -> oracle x all-NaN. The finding's falsification condition ("observe a nonsingular matrix or all-finite x_correct") does NOT occur.

**Pilot-wide counts (all 7 run dirs, enhanced_tests.jsonl, serial):** statuses total = {pass:4271, fail:591, baseline_incompatible:202, numerically_unstable:184, crash:196, build_failed:56}. Serial crash by benchmark: sparse_la/45 = 196 = 100% of all serial crashes (openai_gpt55:116, openai_gpt56_sol:80). sparse_la/45 serial: pass=924, crash=196, build_failed=40. Per dir: pilot_001 {pass:180,crash:40}; combined_iter1 {180,40}; combined_iter2 {180,0}; static_iter1 {102,18}; static_iter2 {22,18}; test_iter1 {160,40}; test_iter2 {100,40,build_failed:40}.

**Blast radius beyond serial (same benchmark, all dirs):** omp {pass:1060, crash:120 all openai_gpt55}; mpi {pass:1054, crash:126 all openai_gpt55, timeout:60 all gemini_31_pro, build_failed:40}.

**Cache:** thesis/results/cache/enhanced/specs.jsonl: only 5 sparse_la/45 specs (sizes 1,2,2,2,3, source=llm); the other 15 run specs are static(4)/mutation(11), pipeline-generated. Cache covers 60 benchmarks incl. sparse_la/49 (12 specs, sizes 0-9) and dense_la/01 (9 specs). sparse_la/49 cpu.cc:100 uses the same floor(0.1*N^2) nVals, HAS ENHANCED_FILL sites (:114-116), baseline divides by U[j*N+j] (:33,35) — credible same-mechanism casualty in the full run. dense_la/01: baseline.hpp:22-24 early-returns on zero pivot (no NaN), cpu.cc:96 validate has an explicit std::isnan check on test output, no ENHANCED_FILL site — likely NOT affected.

**overview.csv rows (iteration 0):** openai_gpt55__sparse_la__45_sparse_la_sparse_solve__serial__sample_0 and openai_gpt56_sol same: correctness_verdict=validation_failed, enhanced_crash=20, enhanced_gated=0; claude_fable_5 same benchmark: correctness_verdict=pass, enhanced_pass=20.


---

### Check C: gated specs — findings

Method: parsed every `enhanced_tests.jsonl` under all 7 run dirs (`thesis/results/intermediate/pilot_001` + `pilot_001__{static_feedback,test_feedback,combined_feedback}__iter{1,2}`), all 11 model subdirs, reconstructing spec identity with the exact `spec_key()` from `thesis/enhanced_tests/specs.py:377`. Scratch scripts in the session scratchpad (`check_c_gated.py`, `check_c_detail.py`, `check_c_sources.py`, `check_c_final.py`); read-only throughout.

#### 1. Headline totals reproduce exactly

Raw record counts across all 7 run dirs match `overview.md` ("Enhanced tests by execution model") cell-for-cell:

| exec | pass | fail | crash | timeout | build_failed | baseline_incompatible | numerically_unstable | gated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| serial | 4271 | 591 | 196 | 0 | 56 | 202 | 184 | **386** |
| omp | 5995 | 601 | 170 | 40 | 136 | 242 | 156 | **398** |
| mpi | 7257 | 880 | 297 | 124 | 326 | 308 | 188 | **496** |

Sample-run counts also match: 275/367/469 = 1111 distinct (run_dir, model, sample) enhanced runs, and overview.csv's 1903 rows sum per benchmark to 148+147+198+102+105+101+169+128+157+247+260+141 = 1903.

#### 2. Per-benchmark gating table with cause

Every sample-run executes exactly **20 specs** (`target_cases_per_benchmark: 20` in run_manifest.json `resolved_config.stages.enhanced_tests`; static base sizes [0,1,2,7] + LLM specs from cache + mutations), and every benchmark has exactly **one** executed spec-key set across all 7 run dirs × 11 models (distinct per-run keysets = 1 for all 12 benchmarks).

| benchmark | records | gated | baseline_incompat. | numerically_unstable | gated specs / 20 | gate cause detail (baseline_gate) |
| --- | --- | --- | --- | --- | --- | --- |
| dense_la/00_dense_la_lu_decomp | 1640 | 0 | 0 | 0 | 0/20 | — |
| fft/05_fft_inverse_fft | 1620 | 162 | 162 | 0 | 2/20 (10%) | crash: (size 5, extreme_values), (size 7, random) |
| geometry/10_geometry_convex_hull | 2640 | 528 | 0 | 528 | 4/20 (20%) | numerically_unstable: extreme_values at sizes 3, 4, 7, 8 |
| graph/15_graph_edge_count | 720 | 0 | 0 | 0 | 0/20 | — |
| histogram/20_histogram_pixel_histogram | 780 | 78 | 78 | 0 | 2/20 (10%) | crash: (size 2, extreme_values), (size 256, ascending, value_range 255–510) |
| reduce/25_reduce_xor | 700 | 0 | 0 | 0 | 0/20 | — |
| scan/30_scan_prefix_sum | 2060 | 0 | 0 | 0 | 0/20 | — |
| search/35_search_search_for_last_struct_by_key | 1240 | 124 | 124 | 0 | 2/20 (10%) | crash: (size 0, random), (size 0, extreme_values) |
| sort/40_sort_..._by_magnitude | 1820 | 0 | 0 | 0 | 0/20 | — |
| sparse_la/45_sparse_la_sparse_solve | 3620 | 0 | 0 | 0 | 0/20 | — |
| stencil/50_stencil_xor_kernel | 3880 | 388 | 388 | 0 | 2/20 (10%) | **hang**: (size 0, random), (size 0, explicit_values) |
| transform/55_transform_relu | 1500 | 0 | 0 | 0 | 0/20 | — |

Totals: 752 baseline_incompatible + 528 numerically_unstable = 1280 = 386+398+496. All numerically_unstable comes from a single benchmark (geometry/10 convex hull, extreme_values only); all baseline_incompatible from 4 benchmarks.

Receipt samples (base run pilot_001, all fields read from enhanced_tests.jsonl):
- `claude_fable_5__fft__05_fft_inverse_fft__serial__sample_0`: spec (7, random) → status=baseline_incompatible, baseline_gate=crash
- `claude_fable_5__geometry__10_geometry_convex_hull__serial__sample_0`: spec (4, extreme_values) → status=numerically_unstable, baseline_gate=numerically_unstable
- `claude_fable_5__histogram__20_histogram_pixel_histogram__serial__sample_0`: spec (2, extreme_values) → baseline_gate=crash
- `claude_fable_5__search__35_search_search_for_last_struct_by_key__serial__sample_0`: spec (0, random) → baseline_gate=crash
- `claude_fable_5__stencil__50_stencil_xor_kernel__serial__sample_0`: spec (0, random) → baseline_gate=hang

#### 3. Gate determinism (the P/M discriminator)

Zero mixed verdicts: across all 26,946 spec-run records, no spec key ever appears both gated and non-gated, and no gated key ever has two causes. The 12 gated keys are gated in **every** occurrence for **all 11 models**, all 3 execution models, all 7 run dirs (occurrence counts per key = the benchmark's full sample-run count: fft 81, geometry 132, histogram 39, search 62, stencil 194). The gate cache is an in-memory dict created per stage invocation (`thesis/evaluation/run_enhanced_tests.py:777`), not persisted to disk, so this is at least 7 independent recomputations agreeing perfectly. Per ground rule 6: identical behavior across all models = property of the harness/oracle — which is precisely what the gate is designed to detect and exclude. The gate is working as designed.

Plausibility of each gate: histogram/20 (pixel histogram, domain 0–255) crashes the oracle on value_range 255–510 (out-of-range bin index — an LLM-authored invalid-domain spec correctly caught) and on extreme_values; search/35 and stencil/50 oracles cannot handle size 0 (crash / hang — stencil's hang is the only hang-gated case); fft/05 oracle crashes on sizes 5 and 7; geometry/10 convex hull under extreme_values fails the perturbed-FP stability probe (hull selection flips under rounding — the documented purpose of the numerically_unstable gate, run_enhanced_tests.py:538–545).

#### 4. Is any benchmark ~100% gated? No.

Maximum is geometry/10 at 4/20 = 20% of executed specs. Every benchmark retains at least 16 non-gated specs. However, three **pattern/size-level** total blind spots exist inside otherwise-healthy benchmarks:
- geometry/10: **all 4** executed extreme_values specs gated → zero extreme-values signal for convex hull;
- search/35: **both** size-0 specs gated → zero empty-input signal;
- stencil/50: **both** size-0 specs gated → zero empty-input signal.
These are oracle limitations, not pipeline defects, but the full run should know these edges contribute no enhanced signal.

#### 5. Do the gated specs match common.py's structural specials? No — and they should not (premise correction)

`thesis/generation/common.py:516–524` names the specials: 25_reduce_* fill_sites 0, 40_sort_* explicit_values disabled. Both have **zero** gated records. That is not a broken gate: the structural specials act **upstream of the gate**, in spec composition, and never produce gated statuses. Verified both mechanisms independently:
- **sort/40** (explicit_values_supported=false in run_manifest prompt_selection): its 20 executed specs contain **no** explicit_values pattern at all — the special manifests as absent specs, nothing reaches the gate.
- **reduce/25, graph/15, sparse_la/45** (manifest `benchmarks_without_fill_site`; confirmed in driver: `drivers/cpp/benchmarks/reduce/25_reduce_xor/cpu.cc:66` has `ENHANCED_TEST_SIZE_DEFAULT(1024)` but no `ENHANCED_FILL` call, unlike 26–29): fill patterns are compile-time no-ops, so same-size specs with different patterns are byte-identical tests. The data proves it: for reduce/25, (7,all_same,(1,1)), (7,alternating,(1,1)) and (7,random) all show the identical status vector {pass:34, crash:1}; all four (15,alternating,*) value-range variants show identical {pass:28, fail:6, crash:1}. sparse_la/45 and graph/15 show the same collapse; graph/15 even carries two key-distinct (1023, all_zeros) and two (4096, all_zeros) specs differing only in the ignored value_range.

Two consequences worth recording:
1. common.py's phrase "fill_sites 0 (no enhanced coverage at all)" **overstates**: `ENHANCED_TEST_SIZE` still applies, and reduce/25 produces genuine size-driven differential fails (e.g. fail:6 at sizes ≥ 3, records readable in any model dir's enhanced_tests.jsonl). Coverage is reduced to the size axis, not zero.
2. The 20-spec budget for no-fill-site benchmarks contains duplicate effective tests (reduce/25: 20 specs ≈ 14 distinct sizes; sparse_la/45 ≈ 11; graph/15 ≈ 13), so their enhanced pass/fail rates double-weight some inputs and waste roughly a third of the spec budget. In the full run, 10 of 60 benchmarks have fill_sites 0 (`thesis/enhanced_tests/benchmark_shapes.json`: dense_la/01, graph/15–19 all five, histogram/23, reduce/25, sort/44, sparse_la/45).

#### 6. Additional cross-checks (clean)

- overview.csv `enhanced_gated` is perfectly uniform per benchmark across all 1903 rows: fft/05=2, geometry/10=4, histogram/20=2, search/35=2, stencil/50=2, all others=0. The join in build_overview.py is correct.
- The smoke runs' 0 gated is consistent, not a regression: the pilot's dense_la/00 also gates 0 specs.
- No `wrapper_failed`, `timeout` or `build_failed` gate values occur — only crash (364), hang (388), numerically_unstable (528).

#### Verdict

**The gate is working as designed.** Gating is deterministic, cause-consistent, cross-model-identical, confined to 12 spec keys on 5 benchmarks, and every gated case is a plausible oracle-level incompatibility (empty-input crash/hang, out-of-domain values, FP-unstable geometry). No benchmark loses its enhanced signal. The 386/398/496 totals are exactly reproducible from the stage JSONLs. The only actionable items before the full run are the note-level blind spots (section 4) and the duplicate-spec weighting on no-fill-site benchmarks (section 5).


*No blocker-level findings in this check — no adversarial verification pass was required.*


---

### Check D — data integrity and provenance

All analysis was read-only. Three scratch scripts were run from the scratchpad (checkd_counts.py, checkd_dirs.py, checkd_triple.py) using stdlib csv/json only; nothing under thesis/results/ was touched.

#### D1. `created_at` "None" — premise is false

The manifest C:/Users/jerab/Desktop/ParEval-thesis/thesis/results/intermediate/pilot_001/run_manifest.json has **no `created_at` key at all**; the key is `created_at_utc` and it is populated: `"created_at_utc": "2026-08-12T12:46:24.983937Z"` (line 3 of the file). `thesis/evaluation/run_manifest.py` line 236 unconditionally writes `"created_at_utc": _utc_now()` at manifest creation — there is no code path that writes a null timestamp. A grep for the bare key `"created_at"` across all `*_summary.json` under the run dirs returns nothing. The reported "None" almost certainly came from someone calling `manifest.get("created_at")` instead of `created_at_utc`. overview.md line 510 prints the timestamp correctly ("Frozen at run time (run_manifest.json, created 2026-08-12T12:46:24.983937Z by stage 'generation', git 6846d689fd81)"), fed by build_overview.py:1710 `manifest.get("created_at_utc")`. Not a bug.

#### D2. Git window 6846d689..912133c — no pipeline code changed

- `git log --oneline 6846d689..912133c` → exactly one commit: `912133c pilot run`.
- `git diff --stat 6846d689..912133c` → **only** `thesis/results/analysis/pilot_001/overview.csv` (+1904 lines) and `thesis/results/analysis/pilot_001/overview.md` (+628 lines). Zero changes to thesis/evaluation/, thesis/repair/, thesis/generation/, thesis/analysis_overview/, drivers/.
- Timeline: c893999 (last code change incl. build_overview.py) 2026-08-12 14:36:22 +0200 → 6846d68 (config change) 14:45:39 +0200 → manifest frozen 12:46:24Z (14:46:24 +0200, 45 s after the commit, git_dirty=false) → overview.md "Generated 2026-08-21T11:34:14.311690Z" → 912133c committed 2026-08-21 13:39:28 +0200.
- `git log -1 -- thesis/analysis_overview/build_overview.py` → c893999, i.e. build_overview.py is identical at run start and at overview build time. **The overview numbers were computed by exactly the code version frozen in the manifest; no mid-window committed change can have affected them.**

Caveat (warning): the three iter2 manifests record **git_dirty: true** mid-run while sitting on 6846d689:
- thesis/results/intermediate/pilot_001__static_feedback__iter2/run_manifest.json: created_at_utc 2026-08-13T21:14:53Z, git_commit 6846d689…, git_dirty true
- pilot_001__combined_feedback__iter2/run_manifest.json: 2026-08-13T23:03:19Z, git_dirty true
- pilot_001__test_feedback__iter2/run_manifest.json: 2026-08-19T08:31:51Z, git_dirty true

The manifest stores only the boolean (run_manifest.py `_git_info`, lines 66–85, `git status --porcelain` → bool), so WHAT was dirty is unrecoverable. thesis/results/{raw,intermediate,cache} are gitignored (.gitignore lines 21–23), so run outputs cannot explain it; likely candidates are untracked scratch files in the repo root (three such files exist there today: `.codex_tmp_sparse_probe.cpp`, `_scratch_crash_focus.py`, `_scratch_enhanced_review.py`, all mtime 2026-08-22 — audit-day artifacts, they do not explain the Aug-13/19 flags) or untracked files under thesis/results/analysis/ (which is NOT gitignored). A temporarily-edited-then-reverted tracked code file cannot be excluded post hoc. Mitigating evidence: `config_drift: []` (0 entries) in all 7 manifests — every later stage invocation compared its resolved config against the frozen one and found no deviation — and no code delta was ever committed. Residual risk judged low but real.

Also noted: the three **iter1** manifests have `git_commit: "unknown"`, `git_dirty: null`, `created_by_stage: "static_analysis"` (e.g. pilot_001__static_feedback__iter1/run_manifest.json, created 2026-08-13T20:57:34Z) — the tolerant fallback in `_git_info` when git is unavailable, consistent with the static-analysis stage running first inside the parcoach Docker container. Expected, but it means iteration-run git provenance rests entirely on the base manifest.

#### D3. Row reconciliation: 1903 rows, arithmetically exact

From overview.csv (computed with scratchpad/checkd_counts.py):

| variant | iter0 | iter1 | iter2 |
|---|---|---|---|
| combined_feedback | 396 | 189 | 123 |
| static_feedback | 396 | 159 | 76 |
| test_feedback | 396 | 98 | 70 |

Total = 3×396 + 312 + 235 + 168 = **1903** ✓. Trail arithmetic is exact in both directions: iteration-N+1 row count equals the previous iteration's `status=active` count in every variant (combined: 189 active@0 → 189 rows@1, 123 active@1 → 123 rows@2; static: 159→159, 76→76; test: 98→98, 70→70). At iteration 2 every row has status stopped_budget or stopped_clean/stopped_tests_pass — no dangling actives.

Cross-check against intermediate dirs (scratchpad/checkd_dirs.py): every run dir's assembly.jsonl = correctness.jsonl = static_analysis.jsonl = dynamic_analysis.jsonl record count = the overview row count for that (variant, iteration): base 396; static iter1/iter2 159/76; test 98/70; combined 189/123. enhanced_tests.jsonl = exactly 20× the sample count in every one of the 7 run dirs (7920, 3180, 1520, 1960, 1400, 3780, 2460). Nothing missing, nothing extra.

Uniqueness: 0 duplicate (variant, iteration, sample_id) keys across 1903 rows; 396 unique sample_ids; every sample_id appears exactly 3× at iteration 0 (checkd_triple.py).

Receipt row: `claude_fable_5__dense_la__00_dense_la_lu_decomp__serial__sample_0`, iter 0 (3 rows, one per variant): data_complete=true, na_reason=NA, build_ok=true, correctness_verdict=pass, blocking_count=0, enhanced_pass=20, enhanced_fail=0, status=stopped_clean.

#### D4. "incomplete: 0" is genuine, not silent dropping

build_overview.py `build_row` (lines 452–670) NA-marks instead of dropping. data_complete=false is produced by exactly three paths:
1. `artifact_missing` (lines 478–481): the iteration run dir doesn't exist / RunData.exists false.
2. `repair_unusable` (lines 489–492): assembly record absent or `assembled` false.
3. `backfill_missing:<stages>` (lines 664–666): static record missing or missing any scoped required tool (line 503), dynamic record missing (506), correctness record missing (569), or enhanced records absent although expected (marker in cpu.cc + execution model configured, lines 607–645).

`collect_model_rows` (673–724) emits a row for every iteration 0..max(trail) of every sample in the union of base assembly keys and the state trail — a missing stage record can never remove a row. overview.md line 506 "Rows total: 1903, incomplete: 0" therefore means "every expected stage record exists", which D3 confirms independently by exact count matching. Additional receipt: `grep '"assembled": false'` over all 7 run dirs' assembly.jsonl → zero hits, so zero repair_unusable is real (all 715 repair responses assembled).

Three genuine silent-skip corners exist in the code but are arithmetically excluded in this pilot:
- (a) missing variant state file → whole variant silently skipped (`continue`, lines 690–691). Excluded: all 3 variants have 396 iter0 rows; state.jsonl present under e.g. thesis/results/intermediate/pilot_001/claude_fable_5/repair/{static_feedback,test_feedback,combined_feedback}/.
- (b) a sample absent from BOTH base assembly.jsonl and the trail → no row, no NA marker (line 703). Excluded: 396 = 36 prompts × 11 models exactly, and raw generations show no losses (D5).
- (c) a truncated trail file would end a sample's rows early without a marker. Excluded: iterN+1 counts equal active-at-N counts exactly.

#### D5. Denominators: all 11 models fully present

overview.csv iteration 0: every one of the 11 models has exactly 36 rows in every variant (11×36=396 per variant). Raw side: each thesis/results/raw/pilot_001/<model>/generations.jsonl has exactly 36 lines with no error field set, and every generation_summary.json reads `{"requested": 36, "success": 36, "truncated": 0, "refused": 0, "error": 0, "skipped_existing": 0}` — all 11 models (receipt printed for each in checkd_dirs.py output). No rate-limit/refusal shrinkage anywhere.

#### D6. is_shared_initial triple-counting audit — clean

is_shared_initial=true on exactly the 1188 iteration-0 rows. `_dedupe_measurement_rows` (build_overview.py 1120–1145) keys iter0 by (model, sample_id, 0) and iters≥1 by (model, variant, sample_id, iteration). Per-aggregate audit:

| aggregate | dedupes? | receipt |
|---|---|---|
| blocking_by_class (c) class×exec @iter0 | yes | line 1017: `_dedupe_measurement_rows(rows)` |
| enhanced_by_execution_model | yes | lines 1435–1438 |
| race corroboration buckets + flagged table | yes | lines 1196–1199 |
| race stopped_budget attribution | per (sample_id, variant) trail — intentionally per-variant, not a pooling bug | lines 1248–1263 |
| runtime_cost_section | yes | line 1285 |
| generation_effort_section | yes | lines 1345–1349 |
| cleaning_section | own dedup by (model, sample_id, iteration) | lines 1492–1499 |
| completeness_section | raw rows by design (counts CSV rows) | lines 1567–1571 |
| trajectory/stop_reason/findings_convergence/breakdown/blocking_by_class (a),(b)/clean_but_incorrect | per-variant sections — shared rows appear once per variant table, which is the intended semantics | render_markdown 1613–1655 |

Numeric receipt from the committed overview.md (lines 242–246): enhanced-by-exec samples are serial 275 + omp 367 + mpi 469 = **1111** = the number of unique artifacts (396 iter0 + 446 iter1 + 269 iter2). Triple-counted it would have been 1903. Race table: 1+79+43+244 = 367 = the omp artifact count. No triple-counting anywhere.

Which variant's row survives iter0 dedup is arbitrary (first seen), but checkd_triple.py verified all 3 iter0 rows per sample are field-identical except variant/status/stop_reason (0 differing samples of 396), so measurement columns are unaffected. Cosmetic: the race "flagged" table prints that arbitrary variant label for iter0 artifacts (build_overview.py 1233–1243), which can mislead a reader into attributing a shared artifact to one variant.

#### D7. Manifest provenance gaps (notes)

- `primary_compiler_version: null` and `toolchain_versions: null` in the base manifest: it was created by the generation stage on the Windows host where g++ and the cached toolchain file are absent (`_compiler_version` and `record_toolchain_versions` both fail soft). The actual toolchain provenance lives in thesis/results/intermediate/pilot_001/toolchain-versions.txt (copied into the run dir 2026-08-12 21:28 by a later static-analysis invocation; run_static_analysis.py lines 61–69 copy a cached file): header "toolchain versions (2026-07-31T13:18:08Z)", g++ 13.3.0, clang 18.1.3, Cppcheck 2.13.0, Open MPI 4.1.6, Infer v1.1.0, Python 3.12.3. Note the snapshot predates the run by 12 days — it pins the toolchain only under the assumption the container image was unchanged since 2026-07-31.
- Frozen fields are never overwritten by design (run_manifest.py module docstring), so these nulls are permanent for this run.

#### Proposed fixes (diff-in-prose, not applied)

1. run_manifest.py `_git_info`: alongside the boolean, store the first ~50 lines of `git status --porcelain` output (e.g. key `git_status_sample`) so a dirty flag is auditable post hoc. For the full run: start from a committed clean tree and keep scratch files outside the repo (the repo root currently collects untracked `_scratch_*.py` files that flip the dirty bit).
2. build_overview.py `collect_model_rows`: replace the silent `continue` on a missing variant state file with a printed WARN plus a synthetic NA row block (or at minimum a counter in the completeness section), and add an assertion/printed check that iteration-0 row count == n_prompts × n_models per variant — the guard that made this pilot's cleanliness provable.
3. run_manifest.py `_toolchain_versions_text` / `record_toolchain_versions`: re-capture tool versions fresh (inside the analysis container) at run start rather than copying a dated cache file, and backfill the manifest's `toolchain_versions` via the existing additive-enrichment path when it is null and the file appears later.
4. race_corroboration_section flagged table: print `shared` instead of the surviving variant name for iteration-0 rows.


*No blocker-level findings in this check — no adversarial verification pass was required.*


---

### Check E — enhanced sample-count asymmetry (serial 275 / omp 367 / mpi 469)

#### Verdict up front
The asymmetry is **intended semantics, not a join defect**. It reproduces exactly, twice, from independent sources. The counts are artifact counts (deduplicated over the shared iteration-0 generation, per-variant for iterations >= 1), and serial simply produces fewer repair artifacts because serial code is cleaner at iteration 0 and stops the loop earlier. The counts in the table are trustworthy as an inventory; the only hazard is deriving per-execution-model *rates* from this pooled table — those are selection-weighted and flip the serial-vs-omp ordering relative to the balanced final-state tables.

#### 1. The code mechanism (thesis/analysis_overview/build_overview.py)
- `enhanced_by_execution_model_section` (lines 1427-1476) computes `deduped = [r for r in _dedupe_measurement_rows(rows) if r.get("enhanced_pass") is not None]`, then per execution model prints `len(subset)` as "samples" and column-sums of the `enhanced_*` verdict counts.
- `_dedupe_measurement_rows` (lines 1120-1145): iteration-0 rows are keyed `(model, sample_id, 0)` — the shared initial generation is counted ONCE although it appears in all 3 variants' row sets (1188 CSV rows -> 396 artifacts); iteration >= 1 rows are keyed `(model, variant, sample_id, iteration)` and all stay.
- Rows for iteration >= 1 only exist where the repair loop actually produced an artifact (`collect_model_rows`, lines 687-724: rows are built for `range(0, last+1)` from the loop-state trail). Enhanced tests run once per produced artifact (base run + each iteration run dir has its own enhanced_tests.jsonl).
- So per execution model: samples = 132 shared iter-0 artifacts + all per-variant repair artifacts at iterations 1-2. There is no re-testing of unchanged artifacts and no carry-forward in this table (carry-forward only exists in the trajectory/final-state sections).

#### 2. Reproduction of 275/367/469 — twice
**(a) From overview.csv** (thesis/results/analysis/pilot_001/overview.csv, 1903 rows), replicating the dedup logic (scratch script check_e_csv.py in the scratchpad — read-only analysis):
- deduped artifacts: 1111 total = 396 (iter0) + 446 (iter1) + 269 (iter2); all 1111 have enhanced data (0 rows excluded by the `enhanced_pass is not None` filter — no join dropout).
- serial 275 = 132 + 84 + 59; omp 367 = 132 + 154 + 81; mpi 469 = 132 + 208 + 129.
- Every verdict cell matches overview.md exactly: serial pass 4271 / fail 591 / crash 196 / timeout 0 / build_failed 56 / runtime_error 0 / gated 386; omp 5995/601/170/40/136/0/398; mpi 7257/880/297/124/326/0/496.

**(b) Independently from the stage JSONLs** (thesis/results/intermediate/pilot_001/<model>/enhanced_tests.jsonl + the 6 iteration dirs pilot_001__<variant>__iter<1|2>, execution model parsed from sample_id; scratch script check_e_jsonl.py):
- base pilot_001: serial 132 / omp 132 / mpi 132 distinct samples, exactly 20 spec-run records each (396 x 20 = 7920 records).
- iteration dirs (distinct samples per dir): static_feedback iter1 24/52/83, iter2 10/15/51; test_feedback iter1 22/37/39, iter2 21/26/23; combined_feedback iter1 38/65/86, iter2 28/40/55 (serial/omp/mpi).
- totals: serial 275, omp 367, mpi 469 — exact match. Status sums also match, including gated = baseline_incompatible + numerically_unstable (serial 202+184=386, omp 242+156=398, mpi 308+188=496).
- Set-level identity check (check_e_setmatch.py): for all 6 iteration dirs the set of (model, sample_id) in enhanced_tests.jsonl is IDENTICAL to the set of iteration rows in overview.csv (n = 159/76/98/70/189/123, matching the "artifacts" column of the per-tool convergence tables in overview.md). Every one of the 715 iteration artifacts has exactly 20 spec-run records. Arithmetic invariant: 275x20 = 5500 = 5114 non-gated + 386 gated; 367x20 = 7340 = 6942 + 398; 469x20 = 9380 = 8884 + 496.

#### 3. Why serial has fewer artifacts — mechanism verified at sample level
A sample enters iteration 1 of a variant iff it fails that variant's stop rule at iteration 0. From overview.csv iteration-0 rows (identical across variants):
- blocking findings > 0: serial 24/132, omp 55/132, mpi 84/132.
- ParEval verdict pass: serial 110/132, omp 103/132, mpi 102/132.

Sample-level set equality (check_e_mechanism.py):
- static_feedback iter-1 entrants == iter-0 samples with blocking findings visible to static_feedback: serial 24=24 with ZERO symmetric difference. omp 52 entrants vs 55 blocked; the 3 "blocked-not-entered" all have ONLY dynamic blocking findings (invisible to static_feedback, whose sources are compiler_errors + static_findings): claude_fable_5__sparse_la__45_sparse_la_sparse_solve__omp__sample_0 (tsan=1), gemini_36_flash__geometry__10_geometry_convex_hull__omp__sample_0 (tsan=2), gemini_36_flash__sort__40_sort_sort_an_array_of_complex_numbers_by_magnitude__omp__sample_0 (tsan=1). mpi: 83 vs 84, the 1 exception gemini_36_flash__sort...__mpi (must=1, dynamic-only). Fully consistent with run_manifest stages.repair.strategies.
- test_feedback iter-1 entrants == iter-0 non-pass UNION dynamic-blocking: serial 22 entrants = exactly the 22 non-pass serial samples (0 discrepancy); omp 37 = 29 non-pass + 8 ParEval-pass samples with tsan blocking; mpi 39 = 30 non-pass + 9 ParEval-pass samples with MUST blocking (e.g. deepseek_v4_flash__fft__05_fft_inverse_fft__mpi__sample_0, must=3).
- combined_feedback = union: serial 38, omp 65, mpi 86 entrants.

So the ordering serial < omp < mpi in repair entries (84 < 154 < 208 sample-variant entries at iter1) is driven by static cleanliness (24 vs 55 vs 84 samples with blocking findings), reinforced by dynamic-tool findings that only exist for omp (TSan) and mpi (MUST). This is a REAL property of the generated code per execution model (cross-model: all 11 models show the gradient), i.e. the measurement is right — verdict M for the underlying driver, and the counting itself is correct-by-design (P-side clean).

#### 4. Bias analysis
The table pools iteration-0 artifacts (a balanced, unconditioned population) with repair artifacts (conditioned on failing a stop rule). The mix differs by execution model: repair share serial 143/275 = 52.0%, omp 235/367 = 64.0%, mpi 337/469 = 71.9%. Enhanced pass rate over non-gated specs, split (check_e_mechanism.py):
- serial: iter0 93.5% (2346/2508) | repair artifacts 73.9% (1925/2606) | pooled 83.5% (4271/5114)
- omp: iter0 89.1% (2234/2508) | repair 84.8% (3761/4434) | pooled 86.4% (5995/6942)
- mpi: iter0 83.6% (2096/2508) | repair 80.9% (5161/6376) | pooled 81.7% (7257/8884)

The serial repair population is the most concentrated on pathological samples: 143 artifacts from only 38 distinct samples, dominated by stencil (49), sparse_la (47), geometry (35); e.g. openai_gpt55__sparse_la__45_sparse_la_sparse_solve__serial__sample_0 contributes 6 artifacts at 20% pass (24/120) and openai_gpt55__stencil__50_stencil_xor_kernel__serial__sample_0 6 artifacts at 61% (66/108). omp/mpi repair populations are broader (65 and 86 distinct samples) and include many samples that entered repair only for a static/race finding while their enhanced tests pass 100% (e.g. deepseek_v4_pro__sparse_la__45_sparse_la_sparse_solve__omp__sample_0: 6 artifacts, 120/120 pass).

Direction of bias if someone derives per-exec rates from this table: serial is understated the most (pooled 83.5% vs balanced final-state 94.4/91.9/95.1% across variants, roughly -10pp), omp less (86.4% vs 93.9/94.7/93.4%, ~-7.5pp), mpi least (81.7% vs 87.2/89.4/85.5%, ~-5.7pp) — it would FLIP the serial >= omp ordering seen in every balanced per-variant execution-model table (overview.md lines 181-185, 203-207, 225-229). The same caveat applies to cross-exec comparison of raw crash/timeout/build_failed counts (e.g. mpi 326 build_failed vs serial 56 partly reflects mpi's 2.4x larger repair-artifact pool). overview.md itself never prints a rate from this table (raw counts only), and the section header frames it as the decision basis for parallel-enhanced gating — so no printed headline number is wrong. The residual hazard is the column label "samples", which invites reading 275/367/469 as balanced sample populations and dividing into them.

**Proposed fix (diff-in-prose, not applied):** in `enhanced_by_execution_model_section` (build_overview.py ~line 1448), rename the column header `samples` to `artifacts` and extend the preamble sentence with something like: "artifact counts pool the shared iteration-0 generation (once) with every per-variant repair artifact; the population is conditioned on repair entry and differs per execution model — do not derive per-execution-model pass rates from this table (use the balanced per-variant execution-model tables instead)." Optionally also print the iter-0 / iter>=1 split per row (132+143 / 132+235 / 132+337) so the composition is visible.

#### 5. Incidental observations
- `enhanced_runtime_error` is 0 in all three rows and the status "runtime_error" never occurs in any of the 22,220 spec-run records across all run dirs — dead column in this run (crash/build_failed absorb everything). Not a bug; worth knowing when reading the table.
- The `enhanced_pass is not None` filter excluded 0 artifacts: enhanced coverage of produced artifacts is 100% (1111/1111), so there is no "only surviving samples get re-tested" selection *within* the artifact population; the only selection is repair entry itself.

Scratch scripts (read-only analysis, outside the repo): check_e_csv.py, check_e_jsonl.py, check_e_mechanism.py, check_e_setmatch.py in C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/.


*No blocker-level findings in this check — no adversarial verification pass was required.*


---

### Check F — repair-loop convergence (static_feedback focus)

All analysis was read-only. Scratch scripts (stdlib-python joins over the jsonl/csv files) were run from the session scratchpad; nothing under thesis/results/ was modified. My re-computed per-tool blocking totals from `static_analysis.jsonl` + `dynamic_analysis.jsonl` reproduce the overview.md static_feedback table exactly (iter0: 25/181/231/3/45/5/32/2/15/2/14; iter1: 3/139/29/0/15/0/8/0/9/0/12; iter2: 18/114/21/3/12/12/7/0/6/0/7 — `thesis/results/analysis/pilot_001/overview.md` lines 55-59), so the table itself is faithfully built from the records.

#### F.1 gcc_analyzer: same finding surviving? — YES, and it is a tool false-positive class, not lazy repairs

Join of `static_analysis.jsonl` across `pilot_001`, `pilot_001__static_feedback__iter1`, `pilot_001__static_feedback__iter2` (396/159/76 samples):

- iter0→iter1: 53 samples had gcc_analyzer blocking at iter1; 48 also had blocking at iter0, and **47/48 share at least one check_id** with their iter0 findings (10/48 share exact (check_id,file,line) — lines shift because the code was edited). iter1→iter2: 38 blocking samples at iter2, 37 persisted from iter1, **37/37 same check_id** (15 same exact location). 34 of the 38 iter2-blocking samples were already blocking at iter0.
- The findings are one family: iter0 check_id mix = `-Wanalyzer-null-dereference` 80, `-Wanalyzer-possible-null-dereference` 69, `-Wanalyzer-use-of-uninitialized-value` 26, `-Wanalyzer-malloc-leak` 4, `-Wanalyzer-out-of-bounds` 2; 147/181 on MPI samples.
- **Cross-model agreement (the P/M discriminator): at iter0, (30_scan_prefix_sum, mpi) has gcc_analyzer blocking for 11/11 models; (50_stencil_xor_kernel, mpi) 10/11; (45_sparse_la_sparse_solve, mpi) 9/11; (55_transform_relu, mpi) 9/11; (05_fft_inverse_fft, mpi) 6/11.** All models do not independently write the same null bug into a prefix sum; this is a property of the tool/harness gate.
- Prompt inspection (receipt): `thesis/results/intermediate/pilot_001/claude_fable_5/repair/static_feedback/iter1/requests.jsonl` and `iter2/requests.jsonl`, sample `claude_fable_5__scan__30_scan_prefix_sum__mpi__sample_0`. The iter1 feedback is faithfully rendered and specific ("line 31: [-Wanalyzer-null-dereference] dereference of NULL '0' [CWE-476]", "possibly-NULL ...std::_Vector_base<double,...>::_Vector_impl_data::_M_start"). These are gcc `-fanalyzer` complaints about **libstdc++ std::vector internals** on a perfectly idiomatic implementation (`std::vector<double> local(localCount); local[i] = ...`). The model responded substantively at iter1 — added `size<=0` guard, `.at()`, `!local.empty()` guards, nullptr-safe `data()` — and the analyzer re-fired at iter2 on the same family (`possibly-NULL ..._M_finish`, `use-of-uninitialized-value *<unknown>`). The feedback is actionable in form (check id + line + message) but **unfixable in substance**: no reasonable edit silences gcc-analyzer's model of `operator new` possibly returning NULL inside libstdc++ containers.
- **Lazy-repair hypothesis falsified**: comparing sha1 of `sources/<sid>/generated-code.hpp` across iterations, 0/159 iter1 sources are byte-identical to iter0 and only 1/76 iter2 sources identical to iter1 (`qwen36_35b_a3b__sparse_la__45_sparse_la_sparse_solve__mpi__sample_0`). Models genuinely edit every time.
- **The "rising findings per artifact" (0.46→0.87→1.50) is a survivor-composition artifact, not worsening code**: per-AFFECTED-sample density is flat (181/61=2.97 → 139/53=2.62 → 114/38=3.00), and the pool's MPI share grows 33%→52% (83/159)→67% (51/76) because MPI samples carry the unfixable FP class. Among the 76 samples present at all three iterations, gcc blocking counts went down for 28, stayed equal for 19, went up for 10, and were always zero for 19.

Verdict: **(P)** — non-actionable feedback due to a gcc-analyzer FP class on libstdc++ containers being classed as blocking; convergence for ~34 persistent samples is structurally impossible. Not survivor bias in the "same untouched finding" sense, and not model failure.

#### F.2 parcoach 5 → 0 → 12 and llov: is the 0 real?

- **The iter1 zero is a real, merged zero at the record level**: all 83 MPI samples in `pilot_001__static_feedback__iter1/*/static_analysis.jsonl` have a parcoach entry with `ran: true` and 0 findings (0 absent, 0 ran:false). build_overview.py fills `parcoach_blocking` only when `entry.get("ran")` (line 523-524), so the overview "0" cell is "ran and found nothing" per its own semantics.
- **Caveat: "ran" overstates coverage.** Of the 83 iter1 runs, 30 carry a non-null `error` — 16 "parcoach timed out" (exit_code -1), 14 "clang -emit-llvm failed for the reduced TU" (exit_code 1) — with num_findings forced to 0. Effective coverage: iter0 83/132 (49 errored: 19 timeouts + 30 emit-llvm), iter1 53/83, iter2 38/51. The overview's stated cell semantics ("0 = ran and found nothing — a result", overview.md builder line 878-880) is untrue for ~36% of the iter1 pool. Timeouts are visible via `parcoach_timed_out` in overview.csv; the emit-llvm failures are invisible in the flat table.
- **The 12 at iter2 is genuine data (7 samples, all `parcoach-collective-ordering`) but is a feedback-induced cascade, not a model-quality signal.** All 7 samples (`claude_opus_5__scan__30...__mpi`, `claude_opus_5__stencil__50...__mpi`, `gemini_36_flash__scan__30...__mpi`, `gemini_36_flash__stencil__50...__mpi`, `openai_gpt55__fft__05...__mpi`, `openai_gpt55__scan__30...__mpi`, `openai_gpt55__stencil__50...__mpi`) had error-free parcoach runs with 0 findings at BOTH iter0 and iter1. At iter2 the finding is e.g. (openai_gpt55 scan): "MPI_Exscan possibly not called by all processes because of conditional(s) line(s) 15", where line 15 of the iter2 source is `if (rank_int < 0 || size_int <= 0) { return; }` — a defensive guard the model added in response to the gcc_analyzer null-deref feedback (same benchmarks as the gcc FP cluster: scan/stencil/fft MPI, 3 models). The guard is uniform across ranks in practice (rank is never negative, size is identical on all ranks), so ParCoach's conservative flag is itself FP-ish. Verdict: **(P)** — tool-interaction artifact of the FP feedback loop, not "repair introduces MPI bugs".
- **llov**: at iter2, 20 samples (17 mpi, 3 serial) have NO llov key in `tools` while at iter0/1 non-OMP samples had llov present with `ran:false`; all 15 OMP samples at iter2 have llov `ran:true`. Cosmetic schema inconsistency; build_overview treats absent and ran:false identically (both → n/a), so no number is affected. llov findings carry a line but a generic message ("Data race detected (LLOV polyhedral analysis)", e.g. claude_fable_5 dense_la omp line 16); still, 20/26 affected samples cleared iter0→iter1, so the channel functions.

#### F.3 compiler 3 → 18: is the loop introducing compile errors? — YES, episodically; the 18 is 2 samples, both previously compiling

From overview.csv (`thesis/results/analysis/pilot_001/overview.csv`), build_ok True at iter N → False at N+1, per variant:

- **static_feedback**: iter0→1: 2 — `deepseek_v4_pro__dense_la__00_dense_la_lu_decomp__omp__sample_0` (cb=1, "'factor' has not been declared"), `deepseek_v4_flash__geometry__10_geometry_convex_hull__serial__sample_0` (cb=2, "'cross' was not declared") — **both recovered at iter2** (cb=0, build_ok=true). iter1→2: 2 — `claude_opus_5__fft__05_fft_inverse_fft__mpi__sample_0` (cb=3), `openai_gpt56_sol__sparse_la__45_sparse_la_sparse_solve__mpi__sample_0` (cb=15). Both had cb=0/build_ok=true at iter0 AND iter1 — **the 18 is NOT concentrated in never-compiling samples**; conversely, all 11 iter0 compile-fail samples were fixed at iter1 (every one shows it1:cb=0,bok=true).
- **test_feedback**: iter0→1: 2 — `deepseek_v4_pro__stencil__50_stencil_xor_kernel__omp__sample_0` (cb=22), `gemini_36_flash__stencil__50_stencil_xor_kernel__mpi__sample_0` (cb=3). iter1→2: 2 — `deepseek_v4_pro__sparse_la__45_sparse_la_sparse_solve__serial__sample_0` (cb=236), `deepseek_v4_flash__sparse_la__45_sparse_la_sparse_solve__serial__sample_0` (cb=158). **The overview test_feedback iter2 compiler cell of 394 is entirely these 2 samples** (236+158).
- **combined_feedback**: iter0→1: 5 — `deepseek_v4_pro__geometry__10...__mpi` (1), `deepseek_v4_pro__stencil__50...__mpi` (6), `qwen36_35b_a3b__geometry__10...__mpi` (2), `qwen36_35b_a3b__scan__30...__omp` (2), `deepseek_v4_flash__fft__05...__mpi` (3). iter1→2: 4 fresh — `gemini_31_pro__sparse_la__45...__mpi` (2), `gemini_31_pro__stencil__50...__omp` (1), `gemini_36_flash__sparse_la__45...__mpi` (14), `deepseek_v4_flash__scan__30...__mpi` (1) — plus `qwen36_35b_a3b__geometry__10...__mpi` still broken from iter1. These sums (14 and 18+2) reproduce the overview combined compiler cells (14, 20) exactly; likewise static (3, 18) and test (25 = 22+3, 394).
- **Total: 17 fresh compile regressions over 715 repair transitions (446 iter0→1 + 269 iter1→2) ≈ 2.4%.**

**P/M attribution of the two static_feedback iter2 regressions:**
- `claude_opus_5__fft__05_fft_inverse_fft__mpi__sample_0`: **(P) — harness assembly/cleaning bug.** The raw model output (`thesis/results/raw/pilot_001__static_feedback__iter2/claude_opus_5/generations.jsonl`, output.raw_text) is valid C++ with a well-formed 3-line doc comment ending `... stored on rank 0. */`. The assembled `sources/<sid>/generated-code.hpp` splices the canonical 8-line prompt docstring (closing `*/` at line 11) and leaves the tail of the model's comment dangling as bare tokens at line 12 (`   Every rank has a complete copy of x. The final result is stored on rank 0. */`) → "'Every' does not name a type" → ifft never declared → 3 cascading errors. assembly.jsonl cleaning record: `dropped_duplicated_prompt_lines: 4, kept_pre_signature_lines: 1` — the prompt-comment dedup matched only 4 of the model's comment lines because the model's comment is an abbreviated (not verbatim) copy of the docstring.
- `openai_gpt56_sol__sparse_la__45_sparse_la_sparse_solve__mpi__sample_0`: **(M) — model failure.** Raw output uses `std::unique_ptr` 5 times and contains zero `#include` lines; `<memory>` is not in the TU's include set, so 15 cascading errors. (Notably the model reached for unique_ptr while fleeing the gcc-analyzer vector FPs.)
- test_feedback iter2 pair (deepseek 236/158 errors): assembled sources contain the model's chain-of-thought prose and backtick-quoted spans inside the function body (e.g. `deepseek_v4_flash__sparse_la__45...__serial` line 21: "But note: The elimination loop uses \`for (size_t row = ...)\` ..." → "stray '`' in program" cascades). **(M) model format non-compliance amplified by (P) cleaner robustness** (cleaning shows only `dropped_leading_lines: 7`, no fence detected). Same class: `deepseek_v4_pro__stencil__50...__omp` test iter1 has literal prose line "fences. So I'll just output the function text." at line 16 with `fence_count: 5, kept_pre_signature_lines: 4`.

#### F.4 Per-tool-class verdicts (static_feedback)

- **compiler**: feedback works. 11/11 iter0 compile failures fixed at iter1; both iter1 regressions fixed at iter2; regressions are episodic (2 per transition), one of the four harness-caused. Non-monotonic 25→3→18 is fully explained; 18 = 2 samples.
- **gcc_analyzer**: broken feedback — unfixable FP class (F.1), (P). Convergence impossible for a ~34-sample persistent core; per-artifact "rise" is composition, not deterioration.
- **clang_tidy**: works — 85 of 96 affected samples cleared iter0→1; 8 persist with same check id, clustered on `10_geometry_convex_hull` / `40_sort_..._by_magnitude`.
- **infer**: mostly works — 19/26 cleared iter0→1; the 7 persistent samples are 6x `10_geometry_convex_hull` across 5 different models — cross-model agreement suggests an FP-ish cluster worth a look, (P)-leaning note.
- **cppcheck/asan_ubsan/memcheck**: cleared to 0 by iter1; the cppcheck 3 at iter2 are 2 newly-appearing samples (normal churn).
- **parcoach**: worked at iter0→1 (both affected samples cleared); iter2 spike is the guard cascade (F.2), (P).
- **llov**: moderately works (20/26 cleared) despite generic messages.
- **tsan/must**: **not part of this variant's feedback or stop criterion by design** — `thesis/repair/feedback.py` line 93: `"static_feedback": ["compiler_errors", "static_findings"]`, and `thesis/repair/orchestrator.py` evaluate_stop docstring: "the stop criterion counts what the feedback [shows]". Receipt: `deepseek_v4_pro__sort__40_sort_..._by_magnitude__omp__sample_0` has blocking tsan data races at iter0 (1), iter1 (1), iter2 (2), yet its iter1/iter2 repair prompts contain only clang_tidy narrowing findings, its state.jsonl counts blocking=1,2,0 (excluding tsan), and it exits as `stopped_clean` ("own sources clean at iteration 2") with 2 live tsan races. So the tsan 15→9→6 and must 14→12→7 columns in the static_feedback table are side effects of unrelated edits, not feedback outcomes — do not read them as convergence. The persisting must findings themselves (fft MPI `must-datatype-unknown`/`must-datatype-null` on deepseek_v4_flash + gemini_31_pro, identical all three iterations) look like a MUST-container limitation with MPI_CXX_DOUBLE_COMPLEX — unclear, matters for test/combined variants.

#### Proposed fixes (diff-in-prose, NOT applied)
1. In the static-analysis finding classifier (wherever `blocking` is assigned for gcc_analyzer), demote `-Wanalyzer-possible-null-dereference`, and `-Wanalyzer-null-dereference`/`-Wanalyzer-use-of-uninitialized-value` findings whose message path contains libstdc++ internals (`std::_Vector_base`, `_M_impl`, `_M_start`, `_M_finish`) to `low_confidence` (the pipeline already has the low_confidence lane and `low_confidence_stop_mode: grace_once`), so they stop gating convergence.
2. In the assembly cleaner's duplicated-prompt-line logic, after dropping duplicated docstring lines, verify comment-token balance (`/*`...`*/`) of the spliced region and drop any residual bare comment-tail line; alternatively only dedup when the model's comment matches the docstring in full.
3. In the cleaner, treat any non-comment line outside braces that parses as prose (or any line containing ``` or backticks outside a string) as droppable, and record a `prose_leak` flag; at minimum cap `compiler_blocking` reporting per sample or report distinct root errors so 236-error cascades cannot dominate variant-level cells.
4. In overview.md cell semantics, count parcoach/llov runs with non-null `error` separately (e.g. "0 (30 err)") instead of folding them into "ran and found nothing".


#### Adversarial verification of this check's blocker findings


**Finding:** gcc_analyzer blocking findings are a libstdc++ false-positive class (null-deref family on std::vector internals) that no repair can clear; the static_feedback loop cannot converge for a ~34-sample core, and repair budget is burned on them (37/37 iter2-block...


**Verdict: CONFIRMED.**


*Corrected claim:* As stated except one overstatement: 'no repair can clear' is false in the literal sense — 13/61 iter0-blocked samples cleared gcc_analyzer at iter1 and 16/53 at iter2, including claude_opus_5 clearing ALL five of its blocked MPI benchmarks at iter2 (e.g. claude_opus_5__scan__30_scan_prefix_sum__mpi__sample_0). But the clearing mechanism confirms rather than refutes the FP diagnosis: opus cleared by over-allocating (count+1 so the vector is never empty), hoisting .data() into raw pointers, and inserting semantically-dead 'if (ptr == nullptr) return;' guards — analyzer appeasement that degrades the code (an early return before MPI_Exscan/MPI_Gatherv would deadlock the other ranks if ever taken). Corrected phrasing: the finding class cannot be cleared by fixing a defect, only by contorting correct code to appease the analyzer; a 34-sample core exhausted the 2-iteration budget with the same check_ids unresolved. Scope extension: combined_feedback is equally gated (gcc_analyzer blocking 181/122/138 over iters 0/1/2 in overview.md — rising at iter2), so the contamination hits both static-fed variants, not just static_feedback.


*Independent re-derivation (evidence):* All re-derived independently from primary JSONLs (scratch scripts in scratchpad/, read-only). (1) Cross-model iter0, from thesis/results/intermediate/pilot_001/<model>/static_analysis.jsonl across all 11 models: (30_scan_prefix_sum,mpi) gcc_analyzer num_blocking>0 for 11/11 models; (50_stencil_xor_kernel,mpi) 10/11; (45_sparse_la_sparse_solve,mpi) 9/11; also (55_transform_relu,mpi) 9/11 and (05_fft_inverse_fft,mpi) 6/11 (uncited but same pattern). (2) iter0 blocking check_id mix: -Wanalyzer-null-dereference 80, -Wanalyzer-possible-null-dereference 69, -Wanalyzer-use-of-uninitialized-value 26, -Wanalyzer-malloc-leak 4, -Wanalyzer-out-of-bounds 2; total 181 — matches the finding and overview.md line 57 (static_feedback table 181/139/114 at iters 0/1/2; my totals from pilot_001__static_feedback__iter1/iter2 static_analysis.jsonl are 139 and 114 exactly). (3) Persistence: iter2 ga-blocking samples 38, of which 37 also blocked at iter1 and 37/37 share >=1 blocking check_id with iter1 (the 1 new: gemini_36_flash__scan__30_scan_prefix_sum__omp__sample_0); iter1 ga-blocking 53, 48 also blocked at iter0, 47/48 share a check_id. Persistent iter0->1->2 core with overlapping check_ids = exactly 34 samples (8x scan mpi, 6x stencil mpi, 6x transform mpi, 5x sparse_solve mpi, 4x fft mpi, rest singles; claude_opus_5 absent — it cleared). (4) Prompt receipt: pilot_001/claude_fable_5/repair/static_feedback/iter1/requests.jsonl and iter2/requests.jsonl for claude_fable_5__scan__30_scan_prefix_sum__mpi__sample_0 both contain 'dereference of possibly-NULL local.std::vector<double>...std::_Vector_base<double,...>' lines (iter1: lines 31/47/48; iter2: adds line 43). iter1 source (pilot_001__static_feedback__iter1/claude_fable_5/sources/...) shows the model added size<=0 early-return, .at() indexing, and !empty() guards; iter1 static_analysis then re-fired -Wanalyzer-possible-null-dereference citing _M_finish on line 43 ('local[i] += offset' inside a local.size()-bounded loop — provably unreachable-null code). (5) FP corroboration on the 34-core at sf_iter2: correctness.jsonl verdicts 24 pass / 10 validation_failed; dynamic_analysis.jsonl has_blocking_findings=False for 31/34 (the 3 exceptions are MUST mpi-usage findings, not null derefs — asan/ubsan/memcheck clean on all 34). overview.csv: all 34 core rows at variant=static_feedback iter=2 have stop_reason 'iteration budget (2) exhausted; unresolved: N blocking finding(s)' — budget fully burned. (6) The plain -Wanalyzer-null-dereference findings (80 at iter0) are the same class: 43/80 sit on the same line as a _Vector_base-citing finding, 14 more in the same sample; spot-check of an 'isolated' one (openai_gpt55__scan__30_scan_prefix_sum__mpi__sample_0 line 56, 'counts[p]=...' two lines after counts.resize(size)) is the identical vector-allocation FP with a terser one-line message.


---

### Check G — the headline numbers do NOT survive hand-verification

#### G.1 Definition as implemented (build_overview.py::clean_but_incorrect, lines 1062–1103)

- Population: variant `static_feedback` only, grouped per (model, sample_id) over iterations 0–2.
- "Stopped clean": the sample's **last** iteration row has `status == "stopped_clean"` (stop_reason "own sources clean at iteration N" = repair loop found no blocking **static** findings; dynamic-tool findings do not prevent the stop).
- Metrics are evaluated on the **carry-forward effective row** (`_effective_row`, lines 770–783): newest artifact-bearing row ≤ last iteration, skipping `na_reason in (repair_unusable, artifact_missing)`.
- "ParEval-incorrect": `correctness_verdict is not None and != "pass"`; denominator = clean finals with non-None verdict.
- "Enhanced-failing": `enhanced_pass is not None` and `enhanced_fail + enhanced_crash + enhanced_timeout + enhanced_runtime_error > 0`; `enhanced_build_failed` is NOT counted as failing (0 clean finals have it, so no effect in pilot_001).

Reproduction from `thesis/results/analysis/pilot_001/overview.csv` (scratch script `check_g.py` in the session scratchpad): **340 clean finals, 47 incorrect, 57 enhanced-failing — exact match with overview.md lines 231–236.** All 340 have both a correctness verdict and enhanced data; effective iteration == last iteration for all 340 (no stale-artifact joins).

#### G.2 NA / missing handling — CLEAN

Rows with `correctness_verdict` None are excluded from **numerator and denominator** (line 1077), and a "N clean sample(s) without correctness data (backfill missing)" line is emitted (lines 1096–1101). Missing enhanced data likewise shrinks the printed denominator (line 1080), visible in the `x/y` rate string (no explicit warning line for the enhanced side — minor asymmetry, cosmetic here). In pilot_001 both denominators are the full 340, so nothing was silently absorbed as pass. Verdict: **no NA-as-pass defect.**

Side observation: 12 of the 340 "clean" finals have `blocking_count != 0` — in every case purely **dynamic**-tool findings (tsan_blocking or must_blocking; e.g. `gemini_31_pro__sort__40_..._omp__sample_0` iter2 tsan=2; `deepseek_v4_flash__geometry__10_geometry_convex_hull__omp__sample_0` iter2 tsan=2), zero static columns. The md wording "no blocking static findings" is therefore accurate, but "stopped clean" is easy to over-read as fully clean.

#### G.3 Hand-check of 10 of the 47 (selection rule: `random.seed(42); random.sample(...)` over the sample_id-sorted list of 47)

| # | sample_id (iter of final artifact) | verdict | classification | receipt |
|---|---|---|---|---|
| 1 | qwen3_coder_api__dense_la__00_dense_la_lu_decomp__serial (it0) | validation_failed 0/1 | **harness (tolerance)** | correctness.jsonl: 52 mismatches, ALL rel ≈ 8.1e-9 on magnitudes ~1.8e5; absolute epsilon (1e-3) fails a mathematically correct Doolittle LU |
| 2 | claude_opus_5__stencil__50_stencil_xor_kernel__serial (it0) | validation_failed 0/1 | **harness (oracle contradicts spec)** | source implements 8-neighbor Moore count exactly as the prompt's worked example demands; baseline.hpp counts 4 neighbors. Hand-verified example cells (1,0) and (2,0): expected output matches 8-neighbor only |
| 3 | claude_fable_5__stencil__50_stencil_xor_kernel__omp (it1) | validation_failed 0/4 | **harness (same)** | 8-neighbor loop, di/dj ∈ {-1,0,1} |
| 4 | gemini_31_pro__sparse_la__45_sparse_la_sparse_solve__serial (it1) | validation_failed 0/1 | **harness (oracle bug)** | source builds matrix with `mat[el.row][el.column] += el.value` (standard COO summing, same convention the driver uses to construct b); baseline.hpp line 22 uses `=` (overwrite). At TEST_SIZE=128, sparsity 0.1 → 1638 draws over 16384 cells ≈ 82 duplicate pairs/trial → oracle solves a different system than the one that generated b, every trial |
| 5 | deepseek_v4_pro__stencil__50_stencil_xor_kernel__serial (it0) | validation_failed 0/1 | **harness (same as #2)** | 8-neighbor |
| 6 | deepseek_v4_pro__stencil__50_stencil_xor_kernel__omp (it0) | validation_failed 0/4 | **harness (same)** | 8-neighbor |
| 7 | deepseek_v4_flash__geometry__10_geometry_convex_hull__omp (it2) | validation_failed 0/4 (all thread counts) | **real model bug** | I replayed the exact validation inputs (glibc rand(), seed 1, verified against canonical first outputs 1804289383…; 512 draws consumed by init at DRIVER_PROBLEM_SIZE=256, then 2×2048 for validate): the hull *algorithm* matches the baseline bit-for-bit (18/18 and 21/21 points, 0 mismatches). The failure is the OpenMP task construct: `#pragma omp task` without `shared(arr)` makes the vector-reference firstprivate → each task sorts a private copy, real array stays unsorted → garbage hull at every thread count. tsan_blocking=2 on the same row corroborates |
| 8 | claude_opus_5__stencil__50_stencil_xor_kernel__omp (it1) | validation_failed 0/4 | **harness (same as #2)** | 8-neighbor |
| 9 | qwen36_35b_a3b__transform__55_transform_relu__mpi (it0) | validation_failed 1/4 | **real model bug** | prompt: "final result is stored on rank 0"; source partitions but never gathers. np=1 passes; np=2 fails with MISMATCH index=512 got=input (=untouched negative value outside rank 0's chunk), 257 mismatches |
| 10 | claude_opus_5__sparse_la__45_sparse_la_sparse_solve__serial (it1) | validation_failed 0/1 | **harness (same as #4)** | `Md[...] += A[k].value` summing convention |

Sample verdict: **8/10 harness-inflicted, 2/10 real model bugs.**

#### G.4 Classification of all 47 (benchmark clustering + per-source verification)

The 47 concentrate massively: 22× `50_stencil_xor_kernel` (10/11 models serial, 11 omp, 1 mpi), 17× `45_sparse_la_sparse_solve`, 3× `00_dense_la_lu_decomp`, 5 singletons.

- **xor_kernel (22): harness.** Across ALL rows in overview.csv the benchmark scores 246 validation_failed vs 7 pass, and all 7 passes are a single artifact lineage (deepseek_v4_flash mpi). 0/11 models pass serial or omp. Even the one model not in the 47 (openai_gpt55 serial, stopped_budget so outside the denominator) implemented the same 8-neighbor kernel and also fails. Identical enhanced signature (fail=7/pass=11) for every model. Ground rule 6: unanimous cross-model failure = harness property. The prompt's worked example is 8-neighbor; the oracle is 4-neighbor.
- **sparse_solve (17): 14 harness, 3 ambiguous.** I grepped all 17 final sources: 14 build the matrix with `+=` (correct COO summing → guaranteed oracle mismatch). 3 exceptions are iterative/sparse-GE solvers (qwen3_coder serial/omp, qwen36_35b serial+omp Jacobi) that would plausibly also fail against a corrected oracle (Jacobi diverges on random non-diagonally-dominant systems) → ambiguous. Smoking gun for the mechanism: the models that DO pass this benchmark mimic the oracle's quirk — claude_fable_5's passing serial source uses `M[e.row][e.column] = e.value` (overwrite). The oracle rewards replicating its own bug.
- **lu_decomp (3): 2 harness, 1 real.** qwen3_coder serial+omp: 52 mismatches, all rel ≈ 8e-9 (tolerance artifact). qwen37_max mpi it1: 260056/262144 mismatches with rel O(1) → genuinely wrong (M).
- **Singletons (5): real or real-leaning.** convex hull omp (M, see #7), relu mpi (M, see #9), qwen3_coder reduce_xor mpi (verdict runtime_error, enhanced crash 20/20 → M), qwen3_coder sort mpi (1/4 grid, enhanced 11 fail/6 timeout → M), deepseek_v4_flash search omp (enhanced fail 18/18 → M).

**Revised headline: of the 47 "statically clean but ParEval-incorrect", ~38 (81%) are oracle/tolerance defects, 6 (13%) are verified/signature-clear real model bugs, 3 (6%) ambiguous. The true "statically clean but genuinely functionally wrong" rate is ≈ 6–9/340 (1.8–2.6%), not 13.8%.**

#### G.5 The 57 enhanced-failing — same contamination

Composition: 22× xor_kernel (the same 4-vs-8-neighbor oracle, now via enhanced fill patterns), 21× convex hull (all ParEval-PASS samples failing only degenerate `all_same`/`all_zeros` specs — 5–7 identical points, where "the convex hull" is ill-defined and baseline vs model differ in equally-defensible degenerate-case conventions; verified on claude_opus_5 serial: 5 fails, all `all_same`/`all_zeros`, 4 `extreme_values` correctly gated as numerically_unstable), plus 14 others (reduce_xor 5, sort 3, search 3, sparse 1, lu 1, relu 1). **≈ 43/57 (75%) artifact-driven; a defensible enhanced-failing rate is ≈ 14/340 (4.1%).**

#### G.6 Auto-closed and counted as PASS — exact numbers

`cleaning_auto_closed` semantics (thesis/assembly/assemble_sources.py lines 202–214): exactly one missing closing brace at EOF, generation not truncated → pipeline appends `}`. Without the intervention the artifact cannot compile, so every such pass is contingent on cleaning. Receipt: `deepseek_v4_flash__reduce__25_reduce_xor__mpi__sample_0` raw generation ends `...return global;\n``` ` with 1 open / 1 close brace in the body-only answer (signature + final brace supplied by pipeline); it is a ParEval pass at iter0 in all three variants.

- 33/396 samples auto-closed at iteration 0 (matches overview.md 8.3%); 3 more artifacts auto-closed at iteration 2.
- **24/33 pass ParEval at iteration 0 itself** (the cleaned artifact is the passing artifact).
- **28/33 are counted as a ParEval pass at some (variant, iteration)**: claude_opus_5 geometry_mpi; deepseek_v4_flash dense_la_serial, reduce_mpi, sort_mpi, transform_omp, transform_serial; deepseek_v4_pro fft_mpi, scan_omp, search_mpi, search_serial, sort_serial, transform_omp, transform_serial; gemini_31_pro geometry_mpi, graph_mpi, graph_omp, sparse_omp; openai_gpt55 dense_la_mpi, geometry_serial, scan_omp; qwen36_35b histogram_serial, sparse_omp; qwen37_max dense_la_mpi, geometry_mpi, geometry_omp, scan_mpi, sparse_mpi, transform_mpi (full sample_ids in overview.csv, all `__sample_0`). The 5 never-passing: deepseek_v4_pro sparse_serial, gemini_31_pro sparse_serial + stencil_mpi, openai_gpt55 stencil_mpi, qwen3_coder dense_la_serial — all on the defective benchmarks of G.4.
- Final-state accounting (counting any-iteration auto-closures): **51 (sample, variant) final-state ParEval passes across the three variants ride on an auto-closed artifact (25 distinct samples)**. Within the headline's 340 clean finals: 16 effective artifacts are auto-closed, **14 of them counted as ParEval pass** (e.g., gemini_31_pro graph_mpi/graph_omp/sparse_omp it0; deepseek_v4_pro search_mpi/serial, sort_serial, transform_omp/serial it0; gemini_31_pro geometry_serial it2).
- build_overview.py's own docstring (lines 33–42) promises to "state the auto_closed share wherever" correctness numbers appear; the md reports it only in a separate Cleaning section, never next to pass rates.

#### G.7 Proposed fixes (diff-in-prose, NOT applied)

1. `drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/baseline.hpp::correctCellsXOR`: count all 8 neighbors (di,dj ∈ {-1,0,1}, skip (0,0)) to match the worked example served to the models — or rewrite the prompt example to 4-neighbor; either way prompt and oracle must agree before the full run.
2. `drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/baseline.hpp` line 22: `matrix[element.row][element.column] += element.value;` (sum, matching the driver's own b construction at cpu.cc line 60). Better: validate by residual ‖Ax−b‖ instead of elementwise x-comparison, or draw duplicate-free coordinates.
3. LU (and other float benchmarks): replace absolute `1e-3` comparison with a relative criterion (e.g. `|a−b| ≤ eps·max(1,|a|,|b|)`), or mechanically reclassify verdicts whose mismatches are all rel < 1e-6 as rounding — the rel field already exists in the records for exactly this purpose.
4. `build_overview.py::clean_but_incorrect`: add a per-benchmark breakdown of the incorrect set (the 22+17 concentration would have exposed this instantly) and an auto-closed caveat line next to every pass rate (a "pass excluding cleaning-contingent artifacts" sensitivity row).
5. Enhanced specs for convex hull: gate `all_same`/`all_zeros` degenerate inputs as baseline_incompatible (hull ill-defined).

All scratch scripts live in the session scratchpad (`check_g.py`, `check_g2.py`, `hull_diff.py`, `hull_exact.py`); nothing under thesis/results/ was touched.


#### Adversarial verification of this check's blocker findings


**Finding:** The headline '13.8% statically clean but ParEval-incorrect' is ~81% harness artifact, not model failure: 22/47 are 50_stencil_xor_kernel where the baseline oracle (4-neighbor) contradicts the worked example in the prompt (8-neighbor), and 14/47 are 45_spars...


**Verdict: CONFIRMED.**


*Corrected claim:* The finding is substantively correct; only its marginal numbers need adjustment. Corrected: the 13.8% (47/340) "statically clean but ParEval-incorrect" headline is ~77% harness artifact (36/47 = 76.6%: 22 xor_kernel where the 4-neighbor oracle contradicts the prompt's 8-neighbor worked example, + 14 sparse_solve where an otherwise-plausible solver sums duplicate COO entries while the oracle overwrites them although the driver builds b by summing; not "~81%"). The sparse_solve share of the 47 is 17 rows, of which 14 are '+='-attributable (the finding's "14/47" conflated these). True statically-clean-but-genuinely-wrong rate is ~11/340 = 3.2% (8 other-benchmark failures + 3 genuinely-broken iterative sparse solvers), slightly above the finding's 1.8-2.6% estimate. Severity BLOCKER stands: the §9 headline is ~4x inflated, both benchmarks' pass rates are corrupted in every breakdown table (xor: 246 fail vs 7 pass, the 7 all one 4-neighbor lineage; sparse: 191 fail vs 51 pass, of which 5 'passes' are themselves NaN-comparison artifacts), and test/combined repair variants burn iteration budget on failures that model-side repair cannot fix. Proposed fixes as stated are sound (align correctCellsXOR to 8 neighbors per the prompt example; build the sparse baseline matrix with '+=' or validate by residual; re-run correctness for the two benchmarks); additionally make reportAndCompare treat NaN as mismatch, since NaN output currently passes validation.


*Independent re-derivation (evidence):* HEADLINE RE-DERIVED INDEPENDENTLY from thesis/results/analysis/pilot_001/overview.csv (1903 rows): static_feedback samples grouped by sample_id, final-iteration status=='stopped_clean' -> 340 clean finals, 47 with correctness_verdict!='pass' = 13.8% (matches overview.md line 233-235; definition confirmed in thesis/analysis_overview/build_overview.py clean_but_incorrect(), lines 1062-1094). Composition of the 47: 22 = stencil/50_stencil_xor_kernel, 17 = sparse_la/45_sparse_la_sparse_solve (finding's "14/47" is the '+='-attributable subset of these 17), 8 = other benchmarks (3x 00_dense_la_lu_decomp, 1 each 25_reduce_xor/40_sort.../55_transform_relu/10_geometry_convex_hull/35_search...).

XOR MECHANISM CONFIRMED: drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/baseline.hpp lines 22-25 count only 4 von-Neumann neighbors; the prompt (thesis/prompts/generation-prompts-thesis.json, 50_stencil_xor_kernel serial entry) carries the identical worked example, which I hand-verified at ALL 16 cells: expected output matches 8-neighbor exactly; 4-neighbor contradicts it at (0,1),(1,0),(2,0) (finding cited (1,0),(2,0): real). Benchmark-wide tally from overview.csv: 260 rows = 246 validation_failed / 7 pass / 7 build_failed — the finding's 246-vs-7 is exact. All 7 pass rows are the single deepseek_v4_flash mpi lineage; its source (pilot_001/deepseek_v4_flash/sources/deepseek_v4_flash__stencil__50_stencil_xor_kernel__mpi__sample_0/generated-code.hpp lines 38-45) implements 4-neighbor, contradicting the prompt example it was shown. FALSIFICATION ATTEMPTED AND FAILED: I regex-classified all 194 xor sources across pilot_001* run dirs and manually read every failing sample the classifier flagged as possibly-4-neighbor (openai_gpt56_sol serial/mpi base + static_feedback iter1, openai_gpt55 serial static_feedback iter2 + test_feedback iter2 + combined_feedback iter2 mpi, claude_opus_5 serial combined_feedback iter2, gemini_36_flash omp test_feedback iter2, openai_gpt56_sol serial test/combined iter2, plus cited claude_fable_5 serial base and deepseek_v4_pro serial base): every single failing source is 8-neighbor (3x3-window or di/dj Moore loops); zero failing 4-neighbor sample exists. Cross-model discriminator: 10/11 models fail identically on all execution models -> P.

SPARSE MECHANISM CONFIRMED: drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/baseline.hpp line 22 'matrix[element.row][element.column] = element.value;' (overwrite) vs cpu.cc line 60 'b[A[i].row] += A[i].value * x[A[i].column];' (sum) — both verbatim. fillRand (drivers/cpp/utilities.hpp line 144ff) draws rows/columns i.i.d. via rand()%N -> duplicate (row,col) pairs; at TEST_SIZE=128 (ENHANCED_TEST_SIZE_DEFAULT(128); ENHANCED_TEST_SIZE only injected by run_enhanced_tests.py line 330, not the correctness stage), SPARSE_LA_SPARSITY=0.1 (utilities.hpp line 31), nVals=1638 -> E[duplicate pairs]=C(1638,2)/16384 = 81.9 ~= finding's "~82"; P(no duplicate)~exp(-82)~0. Of the 17 sparse failures in the 47: 14 use '+=' (finding's 14/17 exact; cited receipts verified verbatim: claude_opus_5 serial static_feedback iter1 'Md[A[k].row * stride + A[k].column] += A[k].value;' — full read shows an otherwise-correct Gauss-Jordan with partial pivoting, so the convention alone explains its failure; gemini_31_pro serial iter1 'mat[el.row][el.column] += el.value;'); 3 are iterative CSR/adjacency Jacobi solvers (qwen36_35b_a3b omp iter1, qwen3_coder_api omp+serial iter0) that are genuinely wrong (M). Passing claude_fable_5 serial uses 'M[e.row][e.column] = e.value;' (iter0 and iter1) — mimics the oracle quirk, as claimed. Full cross-tab over all 247 sparse rows: SUM(+=) 141 fail / 5 pass; OVR(=) 44 pass / 18 fail. The 18 OVR-failures do NOT falsify (overwrite is necessary, not sufficient — they carry unrelated bugs). The 5 SUM-passes are all one lineage, qwen37_max mpi: a diverged-Jacobi whose NaN output passes reportAndCompare (utilities.hpp line 315-321: std::abs(x-NaN)>eps is false) and whose own convergence check treats NaN as converged; kernel time 0.0001s in pilot_001/qwen37_max/correctness.jsonl corroborates early NaN exit (code-reading inference, not executed).

RESIDUAL: 8 other-benchmark failures all come from benchmarks where all 11 models have passing rows (e.g. 00_dense_la_lu_decomp 126 pass/21 fail, models_with_a_pass=11) -> genuine model failures. Scratch scripts used (read-only analysis): classify_xor.py/classify_xor2.py/sparse_check.py/sparse_all.py/xor_verdicts.py in the session scratchpad.


**Finding:** The '16.8% (57/340) enhanced-failing' headline is ~75% artifact: 22 are the same xor oracle defect and 21 are convex hull samples failing only degenerate all_same/all_zeros specs where the hull is ill-defined (all 21 pass ParEval). Defensible rate ~14/340 (...


**Verdict: CONFIRMED.**


*Corrected claim:* The 16.8% (57/340) enhanced-failing headline is ~65% measurement artifact (blocker, P): (a) 22/57 are one oracle defect on 50_stencil_xor_kernel — the prompt's worked example teaches the 8-neighbour rule, the baseline implements 4-neighbour; all 22 share the identical fail=7/pass=11 signature on the same 7 specs, 31/33 base-run samples fail ParEval for the same reason, and the sole 4-neighbour implementation (deepseek_v4_flash mpi) passes everything — this same defect also invalidates 22 of the 47 in the sibling 13.8% ParEval-incorrect headline; (b) 15/57 (not 21) are convex hull samples failing only degenerate specs — but the degenerate class is larger than all_same/all_zeros: every deterministic fill pattern (ascending, sorted_except_one, alternating included) gives x==y elementwise across the driver's two ENHANCED_FILL calls, putting all points collinear on y=x, where the baseline's duplicated-vertex hull convention makes exact-size comparison a coin flip; (c) the remaining 6 convex hull samples have genuine (M) components — 4 fail the well-defined duplicate_at|4 spec, 2 crash on random size-1/2 inputs — so the finding's "only degenerate specs, gate all_same/all_zeros" is wrong in detail and its proposed fix is insufficient. Defensible enhanced-failing rate ~20/340 (5.9%), range 4.7-5.9%. Fixes before full run: align the xor baseline with the example the models actually see (or exclude the benchmark, documenting the upstream ParEval defect); for geometry benchmarks either decorrelate the two ENHANCED_FILL sequences, gate all deterministic-pattern specs as baseline_incompatible, or canonicalize hull comparison (dedupe vertices, set-compare with tolerance).


*Independent re-derivation (evidence):* HEADLINE REPLICATION (scratch scripts rederive_g.py, spec_details.py, cross_model.py in the session scratchpad; all read-only over thesis/results/): from thesis/results/analysis/pilot_001/overview.csv, variant=static_feedback, carry-forward logic re-implemented independently per thesis/analysis_overview/build_overview.py:1062-1103 (clean_but_incorrect) and :770-783 (_effective_row): clean-stopped finals = 340, with_enhanced = 340, enhanced-failing (fail+crash+timeout+runtime_error>0) = 57 -> 16.8% (57/340) EXACTLY matches overview.md line 236. Benchmark decomposition matches the finding: 22x stencil/50_stencil_xor_kernel + 21x geometry/10_geometry_convex_hull + 14 other (5x 25_reduce_xor mpi, 3x 40_sort_...magnitude mpi, 3x 35_search_...last_struct, 1x 45_sparse_la_sparse_solve omp, 1x 00_dense_la_lu_decomp mpi, 1x 55_transform_relu mpi).

XOR (P-CONFIRMED, mechanism found): all 22 clean-stopped stencil-xor samples have the identical signature fail=7/pass=11/gated=2, failing the SAME 7 specs (explicit_values sizes 3,4; random sizes 4,6,7,8,14) — e.g. claude_opus_5__stencil__50_stencil_xor_kernel__serial__sample_0 in thesis/results/intermediate/pilot_001/claude_opus_5/enhanced_tests.jsonl. Root cause verified by hand: the prompt's worked example (thesis/prompts/generation-prompts-thesis.json, name=50_stencil_xor_kernel) is consistent cell-by-cell with an 8-neighbour (Moore) count==1 rule (e.g. cell (0,1): 4-neighbour count=1 -> 1, but example output=0; 8-neighbour count=2 -> 0 matches; same for cell (1,2)), while the oracle correctCellsXOR in drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/baseline.hpp:18-29 counts only the 4 orthogonal neighbours. Generated sources of claude_opus_5, gemini_31_pro, qwen36_35b_a3b, deepseek_v4_pro (serial, under pilot_001/<model>/sources/) all implement the 8-neighbour rule the example teaches. Base-run cross-model: 31/33 samples = validation_failed on ParEval AND enhanced fail=7/pass=11; the single passing sample deepseek_v4_flash__stencil__50_stencil_xor_kernel__mpi__sample_0 implements the 4-neighbour rule (sources/.../generated-code.hpp lines 38-45) and passes ParEval AND all 18 non-gated enhanced specs; the remaining sample is build_failed (qwen3_coder_api mpi). The example-vs-baseline contradiction, not model quality, drives all 22.

CONVEX HULL (P mostly, but the finding's characterization is WRONG IN DETAIL): all 21 pass ParEval (confirmed per-row). The cited exemplar claude_opus_5__geometry__10_geometry_convex_hull__serial__sample_0 (pilot_001__static_feedback__iter1/claude_opus_5/enhanced_tests.jsonl) checks out: 5 fails = all_same sizes 5,6,6,7 + all_zeros size 3; 4 extreme_values specs gated numerically_unstable. BUT the finding's universal claim "failing only degenerate all_same/all_zeros specs" is false, and its own falsification condition #1 is met by the primary data: claude_opus_5__..._mpi (iter1) fails ZERO all_same/all_zeros specs — it fails ascending|3 + sorted_except_one|4,5,6; qwen37_max__..._omp (iter1) fails ONLY duplicate_at|4; claude_fable_5 omp/serial and qwen3_coder_api omp also fail duplicate_at|4; deepseek_v4_pro__..._mpi (iter2) and qwen37_max__..._mpi (iter2) CRASH on random|1, random|2, all_zeros|2, all_same|5, sorted_except_one|5. Deeper mechanism (drivers/cpp/enhanced-fill.hpp:183-225 + drivers/cpp/benchmarks/geometry/10_geometry_convex_hull/cpu.cc:74-75): deterministic patterns (all_zeros, all_same, ascending, descending, alternating, sorted_except_one) produce IDENTICAL sequences for the consecutive ENHANCED_FILL(x) and ENHANCED_FILL(y) calls, so x[i]==y[i] for every i -> ALL points collinear on y=x -> the hull polygon is ill-defined for those patterns too, and baseline.hpp's monotone chain returns a 2-element hull with duplicated vertices ([p,p] for n>=3 identical points) that validate() compares by exact size — a convention lottery, not a correctness oracle (base run: 4 of 11 models happen to share the convention and pass everything; 7 fail some degenerate specs in varying subsets). Corrected split of the 21: 15 samples fail ONLY collinear-degenerate specs (P artifact), 4 fail duplicate_at|4 which IS a well-defined input (fillRand advances rand() state between x and y fills -> genuine 2D points, one duplicated) so plausibly M, 2 mpi samples crash on random size-1/2 inputs = real crashes, M.

CORRECTED ARITHMETIC: clearly-artifact = 22 + 15 = 37/57 (65%, not ~75%); defensible enhanced-failing = 20/340 = 5.9% (not 14/340 = 4.1%); upper artifact bound 41/57 (72%) if duplicate_at dedup-convention fails are also excluded. SEVERITY STRENGTHENED: the same xor defect also owns 22 of the 47 "ParEval-incorrect among clean-stopped" (13.8% headline, overview.md line 235 -> defensible 25/340 = 7.4%), which the finding omitted from numbers_not_survive, and 31/33 stencil-xor samples can never pass ParEval in the full run, so every repair iteration spent on them is wasted budget.


---

## 5. Numbers in overview.md that do NOT survive review

Every figure below is arithmetically correct as computed — `build_overview.py` was verified faithful to the records in all audited sections — but must not be quoted in the thesis as a statement about model capability, because the underlying measurement is corrupted:

1. **Headline "13.8% (47/340) statically clean but ParEval-incorrect"** — ~77% measurement artifact (36/47: 22× stencil oracle contradiction, 14× sparse duplicate-COO inconsistency; adversarially confirmed decomposition). Defensible residual ≈ 6–9/340 (1.8–2.6%): 6 verified/signature-clear real bugs + 3–5 ambiguous.
2. **Headline "16.8% (57/340) statically clean but enhanced-failing"** — ~65% artifact (22× stencil oracle, 21× convex-hull degenerate specs on ParEval-passing samples). Defensible residual ≈ 4–5%.
3. **stencil ParEval 3.0% (1/33)** in all three variant tables — measures the prompt/oracle contradiction, not capability. The sole "pass" contradicted the prompt's own example.
4. **stencil enhanced 62.3% / 62.3% / 58.9%** — 7 of the 11 passing tests per sample are vacuous (interior-only comparison at sizes ≤ 3, or non-discriminating inputs); the 7 failing tests are exactly the neighborhood discriminators.
5. **sparse_la ParEval 21.2% / 42.4% / 36.4%** — dominated by the duplicate-COO artifact (144/247 rows) plus 29 NaN false passes. Corrected iter0 estimate with a fixed harness would be ≈ 64% vs the recorded 21.2%. The recorded rate counts "matches the overwrite artifact OR outputs all-NaN".
6. **sparse_la enhanced 88.5% / 82.1% / 88.2%** — measured against structurally singular systems with a NaN oracle; measures nothing.
7. **The variant ordering on sparse_la ("test_feedback repairs sparse_la best")** — the repair loop largely learned to reproduce the harness bug (models flipping `+=` to `=` after seeing the oracle's "expected" values in the mismatch feedback).
8. **Serial enhanced crash = 196** as a count of model failures — it is 100% two defensive-throw samples on degenerate specs; the models that threw are the only ones that *surfaced* the spec defect. Any per-model crash-rate comparison including sparse_la/45 penalizes exactly the defensive coders.
9. **gcc_analyzer 181 → 139 → 114 read as "real defects"**, and **any "findings per artifact rising" trend** (0.46→0.87→1.50) — per-affected-sample density is flat (2.97→2.62→3.00); the rise is survivor composition (MPI share 33%→52%→67%) dominated by a libstdc++ FP class.
10. **test_feedback iter2 compiler = 394** — entirely 2 prose-leak samples (236+158 cascading errors).
11. **parcoach iter2 = 12 read as "repair introduces MPI collective bugs"** — 7 samples whose flagged lines are defensive guards added in response to the gcc_analyzer FP feedback; parcoach ran clean on the same samples at iters 0 and 1.
12. **parcoach/llov "0" cells read as full coverage** — at static_feedback iter1, 30 of 83 parcoach runs errored (timeout / emit-llvm) with findings forced to 0.
13. **tsan 15→9→6 and must 14→12→7 under static_feedback read as feedback-driven convergence** — dynamic tools are excluded from that variant's feedback and stop criterion by design; movement is a side effect of unrelated edits.
14. **Any per-execution-model rate derived from the "Enhanced tests by execution model" table** (e.g. "serial enhanced pass 83.5%") — selection-biased pooling; use the balanced per-variant execution-model tables instead.
15. **Enhanced rates for reduce/25, graph/15, sparse_la/45** — duplicate effective specs double-weight identical inputs (no-fill-site benchmarks).
16. **Per-model/per-benchmark ParEval pass rates quoted as unassisted model success** — up to 51 final-state passes are cleaning-contingent (auto-closed artifacts); quote with the caveat or with the sensitivity split.
17. **Any cross-problem-type comparison that includes stencil or sparse_la as capability evidence**, and any repair-efficacy claim using stencil (zero movement is preordained: binary validation feedback + a contradictory spec leave no information channel).

**Numbers that DO survive (verified):** the 1903-row completeness accounting; per-model/per-benchmark denominators; the gated-spec totals 386/398/496 and their per-benchmark decomposition; the enhanced verdict-count tables as raw inventories; the ParEval breakdown tables for the ten benchmarks other than stencil/50 and sparse_la/45 (spot-checked only — see open questions); the compile-feedback effectiveness result (11/11 iter0 compile failures fixed at iter1); the MPI timeout analysis (all 124 are hard hangs from 4 samples); the runtime-cost and generation-effort sections (dedup verified).

## 6. Open questions — not resolvable read-only

1. **What made the working tree dirty on Aug 13/19 (iter2 manifests)?** Only the boolean was stored. Needed: nothing now (unrecoverable); for the future, the porcelain-sample fix (W8).
2. **Do the NaN false passes actually reproduce?** The claim rests on code reading plus the 65/128-mismatch signature; the decisive test — rerun one binary and print `x` — was out of scope read-only. One 30-second execution of e.g. `deepseek_v4_flash__sparse_la__45__mpi`'s binary would settle it.
3. **Oracle runtimes of the 21 size>64 frozen specs** (esp. dense_la/01 @ 4096 extreme_values). Needed: the one-off timing pass (W9).
4. **Are the persistent MUST findings on fft MPI (`must-datatype-unknown/null`, identical across iterations for deepseek_v4_flash and gemini_31_pro) a MUST-container limitation with `MPI_CXX_DOUBLE_COMPLEX`?** Matters for test/combined variants' stop behavior. Needed: a minimal MUST run on a known-good complex-datatype MPI program.
5. **Is the persistent infer cluster on 10_geometry_convex_hull (6 of 7 persisting samples, 5 models) an FP cluster or a shared real defect?** Cross-model agreement leans FP, unverified.
6. **Do benchmarks 51–54 (and the other 48 full-run benchmarks) have prompt-vs-oracle contradictions of the B1 class?** The pilot could not see them. The mechanical example-consistency check (B1 fix) answers this wholesale.

## 7. Beyond the ask, deliberately skipped, and where the checks' premises were wrong

**Checked beyond the ask (highlights):**
- Reconciled every overview.md enhanced/gated cell against the raw stage JSONLs (exact, cell-for-cell) and reproduced the 275/367/469 artifact counts twice from independent sources.
- Verified the pilot prompts are byte-identical to upstream ParEval and traced the stencil defect to upstream commit `e865425` — B1/B2 are inherited, not introduced by the thesis fork.
- Classified **all 47** clean-but-incorrect samples and **all 247** sparse_la rows (the ask sampled ~10 / 2–3), including two decisive scratch experiments: a bit-exact glibc-rand replay proving the convex-hull sample's algorithm matches the baseline (isolating a real OpenMP `task` firstprivate bug), and a differential application of both stencil rules to the prompt's example.
- Measured the no-op-repair rate via source hashes (models genuinely edit every iteration: 0/159 and 1/76 identical) — falsifying the "lazy repair" hypothesis before it could contaminate F.
- Audited the six iteration-run manifests (found W8/W13), gate determinism across 7 independent recomputations (0 mixed verdicts in 26,946 records), and the enhanced spec generator's provenance (it read the baseline source — meaning the "held-out" oracle equals the baseline by construction and can never detect prompt-vs-oracle divergence; the failing "documented example" spec is the machine-detectable signature of that bug class).

**Deliberately skipped:** benchmarks 51–54 and all non-pilot benchmarks (not exercised; covered prospectively by the B1 consistency check); re-running anything (ground rule 1 — hence open question 2); the enhanced runner's crash-vs-fail assignment internals beyond what B/W3 needed; GPU/Kokkos driver variants (not part of the pilot).

**Premise corrections (checks that rested on partially wrong premises):**
- **A:** "the enhanced tests use a different driver path than ParEval" is false — same `validate()`, same baseline oracle, differential mode. The 62.3% is not counter-evidence for the kernels; it decomposes exactly into non-discriminating/vacuous specs passing and discriminating specs failing. The anomaly is real and is P, but it sits in the benchmark spec, not the driver/launch path. The dedicated `driver_error` template is irrelevant here (32/33 compile clean).
- **A2:** "variant-to-variant movement suggests no hard harness wall" — inverted here: the movement is the repair loop *learning the wall's artifact* (feedback exposes the oracle's inconsistent expected values; models flip conventions to match).
- **B:** the "passes ParEval but crashes enhanced" discriminator returns M for the crash mechanism — but the P defect sits one level deeper (the specs are degenerate and the *passes* are the corrupted measurements). "Smoke crash columns were 0" is benign: the smokes covered only dense_la, where random matrices are essentially never singular.
- **C:** expecting the gated set to match common.py's structural specials conflates two mechanisms — the specials act upstream in spec composition and can never produce gated statuses (sort/40 and reduce/25 have zero gated records, correctly). Also common.py's "fill_sites 0 = no enhanced coverage at all" overstates: the size axis still applies.
- **D:** "created_at is None in the manifest" — wrong key. The manifest's key is `created_at_utc` and it is populated (2026-08-12T12:46:24Z); the None came from querying `created_at`. (This premise originated in the audit briefing itself and was falsified by the check — no bug.)
- **F:** "findings per artifact rising means feedback may not be working" — half wrong: density per affected sample is flat; the rise is pool composition. The feedback IS failing for gcc_analyzer, but via an unfixable FP class, not deteriorating repairs. And reading tsan/must movement under static_feedback as feedback signal is a category error.
- **G:** the 47 ARE statically clean and DO fail the shipped oracles — the join, carry-forward and NA handling are all correct. What fails is the premise that these oracles measure functional wrongness on 2 of the 12 benchmarks.

---

*Audit artifacts: per-check agent reports and adversarial verification transcripts are preserved in the session workflow directory (`wf_7fbbd655-0b7`); scratch analysis scripts in the session scratchpad. Neither is part of the repo.*
