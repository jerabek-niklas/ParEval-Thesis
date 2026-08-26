# Oracle Audit Calibration — sparse_la/45

Blind-calibration audit of the single benchmark `sparse_la/45_sparse_la_sparse_solve`.
Question: **does the oracle implement the mathematical task defined by prompt and driver?**
Analysis only — no fix implemented, no productive file changed. Date: 2026-08-22.

**Result in one line: 20 reproducible semantic deviations, 14 of them independently re-derived by adversarial verifiers and CONFIRMED, none refuted, none reclassified.** The oracle solves well-posed duplicate-free systems exactly correctly and reproduces the prompt's documented example; it diverges from the posed task on every other axis examined.

---

## Method

### Investigative pipeline

1. Resolved path and name against the repository (`drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/`).
2. Read prompt (all three parallelism entries), `baseline.hpp`, `cpu.cc`, and the shared helpers.
3. Formulated the mathematical invariant independently (below) before writing any probe.
4. Implemented independent references — no line taken from `baseline.hpp`: exact rational Gauss-Jordan (`fractions.Fraction`) for ground truth, plus dense complete-pivoting and partial-pivoting solvers in C++/Decimal for scale tests.
5. Executed: compiled the real oracle into own harnesses, replayed the driver's exact RNG stream, ran the unmodified driver end-to-end with hand-written candidate submissions, ran sanitizer builds.
6. Ran the audit twice over: once by me (orchestrator), and once by **five context-free agents** (four probes + one completeness critic) that began with no knowledge of this session, followed by **14 adversarial verifiers**, each tasked to refute one finding by independent re-derivation.

### Repository files read

By me (orchestrator):

| file | how |
|---|---|
| `drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/` | directory listing |
| `.../45_sparse_la_sparse_solve/baseline.hpp` | full (`cat -n`) |
| `.../45_sparse_la_sparse_solve/cpu.cc` | full (`cat -n`) |
| `drivers/cpp/utilities.hpp` | `grep -n` for constants and comparison helpers; `sed -n '160,200p;240,270p;310,335p'` |
| `drivers/cpp/enhanced-fill.hpp` | `grep -n ENHANCED_TEST_SIZE_DEFAULT -B4 -A10` (lines ~1–30 and 72–90) |
| `thesis/prompts/generation-prompts-thesis.json` | the three `45_sparse_la_sparse_solve` entries, filtered by script |
| `drivers/cpp/` | `grep -rn "struct COOElement"` (filenames and line numbers only) |

By the five blind agents, union (each agent's own list is in its transcript): the four files of the benchmark directory (`baseline.hpp`, `cpu.cc`, `gpu.cu`, `kokkos.cc`), `drivers/cpp/utilities.hpp`, `drivers/cpp/enhanced-fill.hpp`, `drivers/cpp/models/{serial-driver.cc, omp-driver.cc, mpi-driver.cc}`, `drivers/cpp/Makefile`, `drivers/cpp/cpp_driver_wrapper.py`, `drivers/build-configs.json`, `drivers/problem-sizes.json`, `thesis/prompts/generation-prompts-thesis.json`, and a recursive `grep` for `ENHANCED_FILL` over `drivers/cpp/benchmarks/**/cpu.cc` plus the matching lines of the four sparse_la siblings. All within the read allowance ("further `drivers/` files strictly as needed to compile and run"). Deviations and one incident: see *Confidence and blind spots*.

### Scratch files created (all outside the repository)

Under `…/scratchpad/oracle45/`:

- `self/` — mine: `probe_self.cpp` (exact ground truth T1–T9 plus representation variants), `probe_scale.cpp` (driver-stream replica at TEST_SIZE=128; three-way comparison generating-x / oracle / independent solver), `probe_cmp.cpp` (validator NaN/Inf truth table), `probe_sort.cpp` (tie-order dependence), plus binaries.
- `probe-exact/` — `probe.cpp`…`probe7.cpp`, `ref.py` (Fraction-exact reference, both duplicate conventions).
- `coo-rep/` — `probe.cpp`…`probe5.cpp` (representation variants, RNG replay, sort variants).
- `degenerate/` — `probe1.cpp`, `probe2.cpp` (validator truth table), `probe_oob.cpp` (ASan/UBSan), `exact_ref.py` (rank and consistency classification over **Q**).
- `blind/` — `probe.cpp`, `dump.txt` (full dump of both real validation instances: 1638 triplets, b, generating x, oracle output).
- `completeness-critic/` — `probe1.cpp`…`probe7.cpp`, exact-rational certificate scripts, end-to-end submission variants (206 entries).

**Nothing was written inside the repository except this report** (checked by the probes with `git status --porcelain`).

### Representative commands

```bash
# compile a harness against the REAL oracle (repo mounted read-only)
MSYS_NO_PATHCONV=1 docker run --rm -u 0 \
  -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" -v "<scratch>:/scratch" -w /scratch \
  pareval-thesis bash -c "g++ -std=c++17 -O2 \
    -I /repo/drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve \
    probe_self.cpp -o probe_self && ./probe_self"

# validator truth table against the REAL reportAndCompare
g++ -std=c++17 -O2 -DUSE_SERIAL "-DDRIVER_PROBLEM_SIZE=(1<<4)" -I /repo/drivers/cpp probe_cmp.cpp

# end-to-end with the UNMODIFIED driver and a hand-written candidate submission
g++ -std=c++17 -O3 -DUSE_SERIAL "-DDRIVER_PROBLEM_SIZE=(1<<10)" [-DENHANCED_TEST_SIZE=<n>] \
    -I /repo/drivers/cpp -I /repo/drivers/cpp/models -I <candidate_dir> \
    /repo/drivers/cpp/models/serial-driver.cc \
    /repo/drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc -o drv && ./drv 1

# undefined-behaviour classification
g++ -std=c++17 -O1 -g -fsanitize=address,undefined ...
```

---

## Independent invariant

Formulated from prompt and driver before probing, without reference to `baseline.hpp`:

> Let the input be a finite COO list `L = [(r_k, c_k, v_k)]`, `r_k, c_k ∈ [0,N)`, together with `b ∈ R^N` and `N`. The list denotes the matrix `A ∈ R^{N×N}` with
> **`A[i][j] = Σ { v_k : (r_k,c_k) = (i,j) }`** (accumulation over duplicate keys; an absent key means 0).
> `A` is therefore a function of the **multiset** of triples and is invariant under any permutation of `L`.
> "Solve `Ax=b`" means: return the unique `x` with `Ax = b`, which exists iff `A` is nonsingular.
> Verifiable output invariant: the residual `‖Ax − b‖_∞ = 0` up to rounding of order `ε·‖A‖·‖x‖`.

The accumulation rule is **not an imported preference**: the driver itself fixes it, because it builds the right-hand side by accumulating over every COO record —
`b[A[i].row] += A[i].value * x[A[i].column];` (`cpu.cc:59-61`). The generating vector `x_gen` is thus, by construction, the solution of the accumulation-semantics system. Two consequences used throughout:

- **(I1) round-trip:** on driver-generated input a correct solver must return `x_gen` (up to conditioning).
- **(I2) permutation invariance:** the returned `x` must not depend on the order of the COO list.

---

## Test cases

| id | input | purpose |
|---|---|---|
| T1 | the prompt's documented example `A=[{0,0,1},{0,1,1},{1,1,-2}]`, `b=[1,4]` | is the shipped example well-posed and reproduced? |
| T2–T4 | integer `A`, integer `x`, `b = Ax` computed exactly (2×2, 3×3, pivoting-required, rational solution) | **exactly known ground truth** (method step 7b) |
| T5 | `N=1` | degenerate size |
| T6a–T6e | **one** matrix `[[3,1],[1,3]]`, `x=[1,2]`, `b=[5,7]`, in five valid COO representations: canonical, duplicate-split, permuted, explicit zero added, cancelling duplicate pair | **method step 9** |
| T7–T9 | singular (duplicate rows), empty triplet list, zero row | degenerate domain |
| S1 | driver's exact RNG stream replayed at `TEST_SIZE=128`, `nVals=1638`, both validation trials | prevalence at real scale |
| S2 | two equally valid sorted orders of one duplicate-bearing list | tie-order dependence |
| S3 | `reportAndCompare` called directly with NaN/Inf on either side | validator truth table |
| S4 | 20 consecutive driver instances per size at `TEST_SIZE ∈ {8,16,24,32,40,48}`, classified exactly over **Q** | rank and consistency of the posed system |
| S5 | unmodified driver plus hand-written candidate submissions (standard-COO, oracle-convention, NaN-returning, zeros-returning, wrong-size) at `TEST_SIZE ∈ {4…128}` | end-to-end verdicts |
| S6 | out-of-range coordinates, ±DBL_MAX, inf/nan values, `N=0` | sanitizer classification |

Baseline behaviour on the well-posed cases (my run, `probe_self`):

```
T1_doc_example  x=[3, -2]            <- matches the prompt exactly
T2_int_2x2      x=[3, -1]            <- exact
T3_zero_pivot   x=[1, 2]             <- exact (partial pivoting works)
T4_int_3x3      x=[1, 1, 1]          <- exact
T5_N1           x=[0.25]             <- exact
```

**Negative result, reported as a result:** on well-posed duplicate-free systems the oracle's arithmetic is correct, and independent complete-pivoting solvers agree with it to 1e-13 on the *same* matrix. Every finding below is therefore about *which* matrix it solves, or about domain and validation — not about its elimination arithmetic.

---

## Findings

Twenty findings, listed by pipeline location, **not** by severity, and deliberately **not** merged: F1, F3 and F4 share one root mechanism but differ in reachability and consequence; likewise F5/F6/F7. "Verified" means an independent adversarial agent re-derived the finding with its own harness and reference and returned CONFIRMED.

### F1 — Duplicate COO coordinates: the oracle overwrites, the driver accumulates [C] — verified

- **Mechanism.** `correctSolveLinearSystem` materialises the dense matrix with a plain assignment, `matrix[element.row][element.column] = element.value;`. With two or more triples on the same `(row,column)` key only the last in list order survives. The driver builds `b` by accumulating over *every* record, so `b = A_sum · x_gen`, while the oracle solves `A_last · x = b` with `A_last ≠ A_sum`.
- **Reproducing input.** Minimal: `A=[{0,0,1},{0,0,2},{0,1,1},{1,0,1},{1,1,3}]`, `b=[5,7]` (built by the driver's own rule from `x_gen=[1,2]`), `N=2`. Driver-scale: the replayed validation instance at `TEST_SIZE=128`, `nVals=1638`.
- **Expected (independent reference).** `[1, 2]` exactly. At `TEST_SIZE=128` my independent summing solver recovers `x_gen` with `‖x − x_gen‖_∞ = 1.76e-13` (trial 0) and `4.87e-13` (trial 1); residual `‖A_sum x − b‖_∞ ≈ 1e-12`.
- **Oracle result.** `[1.6, 1.8]` on the minimal case. At `TEST_SIZE=128`: `‖x_oracle − x_gen‖_∞ = 183.783` (trial 0) and `44.947` (trial 1), on a solution whose components are bounded by 9.98 — first three components `oracle=[108.43, −138.90, −14.91]` versus `gen=[−6.16, −8.98, 7.99]`. Independent verifiers measured `‖A_sum x_oracle − b‖_∞` of 1116.19 / 379.58 / 585.61 / 826.78 across four trials. The oracle *is* the exact solution of `A_last x = b` (my exact Fraction reference under the last-wins convention reproduces it), so this is a wrong-operation defect, not an arithmetic defect.
- **Driver behaviour.** `validate()` compares with `reportAndCompare(x_correct, x_test, 1e-3)` — absolute tolerance. End-to-end on the unmodified driver: a submission that differs from a passing one **only** by `M[...] += e.value` instead of `M[...] = e.value` prints `MISMATCH_SUMMARY shown=3 total=128` and `Validation: FAIL` (rel 0.33–1.22); the `=` version prints `Validation: PASS`. One character decides the verdict. Verifier's end-to-end table: the mathematically correct standard-COO submission PASSes at `TEST_SIZE` 4/8/16/32/48 but FAILs at 64/96/128; the oracle-convention submission passes at every size — but with `MAX_VALIDATION_ATTEMPTS=100` it FAILs at 32 and 48. The verdict is a function of `(TEST_SIZE, attempts)`, not of the submission's mathematics.
- **Location.** `drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/baseline.hpp:21-23` (`correctSolveLinearSystem`, fill loop) against `.../cpu.cc:59-61` (`createRandomLinearSystem`).
- **Falsification attempt.** (1) Rounding — ruled out: deviations of order 1e2–1e3 with relative deviation ≈ 1; on the *same* matrix `A_last` an independent complete-pivoting LU agrees with the oracle to 1.4e-13. (2) "Summation is merely my convention" — ruled out without appeal to any external convention: the driver's own `b` rule is accumulation, so `x_gen` is by construction the accumulation solution, and only the summing solver recovers it. (3) "Duplicates are too rare to matter" — ruled out: 81 duplicated keys in my trial 0, 81 in trial 1, 68–93 across five independent trials by another probe; never zero. (4) "Generator mis-replicated" — ruled out by running the unmodified `cpu.cc` end-to-end. (5) ASan and UBSan clean on all runs.

### F2 — The graded reference is not a function of the input: unspecified tie order [F] — verified

- **Mechanism.** Because the fill loop assigns, the surviving value at a duplicated key is whichever triple comes **last**. `sortCOOElements` (`cpu.cc:35-39`) uses `std::sort` with a comparator on `(row, column)` only, ignoring `value`; `std::sort` is not stable, so the relative order of equal-key triples — and hence the oracle's answer — is unspecified by the C++ standard.
- **Reproducing input.** My `probe_sort`: multiset `{(0,0,1),(0,0,2),(0,1,1),(1,0,1),(1,1,3)}`, `b=[5,7]`, sorted two ways that both satisfy the driver's comparator (`std::is_sorted` true for both).
- **Expected.** `[1, 2]` (sum convention, permutation-invariant per (I2)).
- **Oracle result.** `[1.6000000000000001, 1.8]` for the driver's `std::sort` order versus `[4, 1]` for the other valid order — neither equals the truth. A verifier's independent minimal case: multiset `{(0,0,2),(0,0,3),(0,1,1),(1,1,4)}`, `b=[7,−12]` gives `[10/3, −3]` or `[5, −3]` depending on which duplicate lands last (exact Fraction confirmation), against a sum-convention truth of a third value.
- **Driver behaviour.** The order the oracle sees is produced by the driver's own sort; the driver never pins it, and the reference vector handed to `reportAndCompare` inherits the ambiguity.
- **Location.** `baseline.hpp:21-23` (order-sensitive materialisation) against `cpu.cc:35-39` (`sortCOOElements`, unstable sort with a comparator that ignores `value`).
- **Falsification attempt.** Checked whether both orders are legitimately "sorted": yes, `std::is_sorted` under the driver's own comparator is true for both, so neither is a corrupted input. Checked whether the two answers could be within tolerance: they differ by 2.4 and 0.8 against an absolute tolerance of 1e-3. One verifier corrected the original claim that the tie order additionally depends on the optimisation level — that clause could not be reproduced and is dropped here; the standard-level unspecifiedness and the element-count dependence stand.

### F3 — An explicit zero triplet deletes an existing entry and can turn a nonsingular system singular [C] — verified

- **Mechanism.** Same assignment as F1, but with value 0: a triple `(i,j,0.0)` following a real entry at `(i,j)` erases it. Under the accumulation convention adding an explicit zero changes nothing.
- **Reproducing input.** `A=[{0,0,3},{0,1,1},{1,0,1},{1,1,3},{1,0,0.0}]`, `b=[5,7]`, `N=2` (T6d).
- **Expected.** `[1, 2]` (the explicit zero is a no-op under accumulation).
- **Oracle result.** `[0.88888888888888884, 2.3333333333333335]` — it solved `[[3,1],[0,3]]`. In a verifier's variant where the erased entry was structurally load-bearing, the matrix became singular and the oracle returned NaN.
- **Driver behaviour.** Graded as the reference; a correct submission is scored wrong.
- **Location.** `baseline.hpp:22`.
- **Falsification attempt.** Reachability: the driver's own `fillRand(A_values, -10.0, 10.0)` produces exact zeros with probability ≈ 0, so this variant is **not** reachable from the driver's generator; a verifier explicitly corrected an overstated reachability claim (the `all_zeros` enhanced pattern does *not* reach it either — see F15). It remains a genuine semantic deviation for any hand-written or externally supplied input, and it is reported as such rather than dropped.

### F4 — A duplicate pair that sums to zero [F] — verified

- **Mechanism.** Under accumulation, `(i,j,+v)` and `(i,j,−v)` make the entry absent; under last-wins the oracle stores `−v`.
- **Reproducing input.** `A=[{0,0,3},{0,1,1},{0,1,5},{0,1,-5},{1,0,1},{1,1,3}]`, `b=[5,7]`, `N=2` (T6e). Verifier's variant: same multiset shape with `b=[10,−12]`.
- **Expected.** `[1, 2]` (mine); verifier's variant `[2, −3]`, recovering `x_gen` exactly.
- **Oracle result.** `[3.5714285714285716, 1.1428571428571432]` (mine); verifier's variant `[−2.2, −3] = [−11/5, −3]` exactly, residual against the sum-convention system 21, residual against the last-wins system 0.
- **Driver behaviour.** As F1.
- **Location.** `baseline.hpp:22`.
- **Falsification attempt.** Checked the "first-wins" reading as an alternative: it gives yet a third answer (`31/5`), so no ordering convention rescues the oracle; only accumulation reproduces `x_gen`.

### F5 — No singularity guard: silent NaN/±Inf [D] — verified

- **Mechanism.** `correctSolveLinearSystem` divides by `matrix[i][i]` at `baseline.hpp:48` (elimination multiplier) and `:62` (back substitution) with no zero-pivot test. Partial pivoting picks the largest candidate but cannot rescue an exactly rank-deficient column.
- **Reproducing input.** T7 duplicate rows `A=[{0,0,1},{0,1,1},{1,0,2},{1,1,2}]`, `b=[2,4]`; T8 empty triplet list, `b=[1,2]`; T9 zero row `A=[{0,0,1},{0,1,1}]`, `b=[2,3]`.
- **Expected.** T7 and T8 are consistent but underdetermined — a finite solution set exists (e.g. `[2,0]` for T7); T9 is inconsistent, so the correct response is "no solution", not a numeric vector.
- **Oracle result.** T7 `[-nan, -nan]`; T8 `[-nan, -nan]`; T9 `[-inf, inf]`. No error signal, no exit code, no diagnostic. A verifier additionally found the non-NaN escape: with a tiny-but-nonzero pivot the oracle returns a **finite, enormous** reference — `max|x_oracle| = 5.32e16` on a driver instance at `N=32` whose generating `x` is bounded by 10, with residual 41.9 against its own last-wins matrix.
- **Driver behaviour.** `validate()` never checks solvability of the system it generated and hands the NaN vector to the comparison.
- **Location.** `baseline.hpp:29-66`, `correctSolveLinearSystem`.
- **Falsification attempt.** Tried to argue this down to "acceptable behaviour on an under-specified prompt": rejected, because (a) the driver *guarantees* consistency by construction in exact arithmetic, so the oracle's NaN is not a response to a malformed input; (b) an independent complete-pivoting solver agrees with the oracle to 1e-10…1e-13 on every nonsingular draw, so the algorithm is not wrong, only its domain is narrower than the driver's input distribution.

### F6 — The validator counts NaN as "equal" [F] — verified

- **Mechanism.** The predicate is `std::abs(x - y) > epsilon` (`utilities.hpp:319`, identically at `:328`, and at `:166` inside `fequal`). Every ordered IEEE-754 comparison involving NaN is false, so a NaN on **either** side makes that index count as matching.
- **Reproducing input.** My `probe_cmp` calls the real `reportAndCompare(a, b, 1e-3)` with one-element vectors.
- **Expected.** A NaN reference is not a valid expected value; a NaN submission is not a correct answer. Either should fail.
- **Oracle/validator result** (executed truth table):

  | expected | got | verdict |
  |---|---|---|
  | 1 | 1 | PASS |
  | 1 | 2 | FAIL |
  | NaN | 42 | **PASS** |
  | NaN | NaN | **PASS** |
  | 42 | NaN | **PASS** |
  | Inf | 42 | FAIL |
  | Inf | Inf | PASS |
  | Inf | −Inf | FAIL |

- **Driver behaviour.** `validate()` uses exactly this predicate as its verdict authority.
- **Location.** `drivers/cpp/utilities.hpp:315-322` (`reportAndCompare`) and `:163-171` (`fequal`).
- **Falsification attempt.** Checked whether `MISMATCH` diagnostics would at least record the anomaly: no — the mismatch counter is driven by the same predicate, so a NaN index is never even printed. Checked whether Inf is caught: yes (except Inf vs Inf), so the hole is specific to NaN.

### F7 — F5 and F6 compose into vacuous validation [F] — verified

- **Mechanism.** Whenever the oracle produces NaN, every index of the comparison passes regardless of the submission.
- **Reproducing input.** Unmodified driver with a candidate that ignores `A` and `b`: returns NaN everywhere, or `1e300` everywhere, or zeros.
- **Expected.** All three must fail.
- **Oracle/validator result.** A NaN-returning candidate passes at the **default** `TEST_SIZE=128`. A `1e300`-returning or zeros-returning candidate passes at every `ENHANCED_TEST_SIZE ≤ 33` and, stream-dependently, at some sizes up to ≈48 (verifier's corrected bound; the original claim said ≤32).
- **Driver behaviour.** Prints `Validation: PASS`.
- **Location.** `baseline.hpp` (NaN production) plus `utilities.hpp:319` (NaN-blind predicate), joined in `cpu.cc:123`.
- **Falsification attempt.** Checked that the passing candidates really are garbage (they never read their inputs); checked that the effect is not an artifact of my compile flags by using the shipped flags from `drivers/build-configs.json`.

### F8 — The known ground truth is generated and then destroyed [F] — verified

- **Mechanism.** `cpu.cc:56` fills `x` with random values; `:58-61` computes `b` from it; `:64` zeroes that same vector. In `validate()`, `:112` passes `x_correct` as that vector, so the generating solution is destroyed, and `:116` overwrites it with the oracle's output. The grading reference is therefore the oracle's answer, never the vector that defined the system.
- **Reproducing input.** Any driver run; my `probe_scale` captures `x_gen` before the wipe.
- **Expected.** With the generating `x` available, the natural reference is `x_gen` itself (or a residual check `‖Ax−b‖`), either of which would have made F1 impossible to miss.
- **Oracle result.** Not applicable — this is a harness-design deviation; its consequence is that the benchmark measures *agreement with the baseline implementation*, not *solving the system*.
- **Driver behaviour.** As described; no round-trip assertion anywhere.
- **Location.** `cpu.cc:56`, `:58-61`, `:64`, `:112`, `:116`, `:123`.
- **Falsification attempt.** Considered whether the oracle's solution is a legitimate reference even if it is not `x_gen`: it would be, if the oracle solved the same system — F1 shows it does not, and F14 shows that at small sizes no solution exists at all.

### F9 — Below N=10 the generator cannot produce a solvable system [F] — verified

- **Mechanism.** `nVals = TEST_SIZE * TEST_SIZE * SPARSE_LA_SPARSITY` with `SPARSE_LA_SPARSITY = 0.1` (`utilities.hpp:29-32`), truncated to `size_t`. For `N < 10` this yields `nnz < N`, so at least one row is structurally empty and the matrix is singular by construction; for `N ≤ 3` the triplet list is entirely empty and `b` is the zero vector.

  | N | nVals | consequence |
  |---|---|---|
  | 1–3 | 0 | empty A, b = 0 |
  | 4 | 1 | ≥3 empty rows |
  | 7 | 4 | ≥3 empty rows |
  | 9 | 8 | ≥1 empty row |
  | 10 | 10 | first size with `nnz ≥ N` |

- **Reproducing input.** `-DENHANCED_TEST_SIZE=<n>` for any `n < 10`; also measured empirically up to 64.
- **Expected.** Either a solvable instance or an explicit refusal to test at such sizes.
- **Oracle result.** NaN (F5), hence automatic PASS (F6/F7).
- **Driver behaviour.** No guard; `validate()` proceeds and reports PASS.
- **Location.** `cpu.cc:99-104` (`validate()` sizing) with `utilities.hpp:29-32`.
- **Falsification attempt.** Checked the default path: at `TEST_SIZE=128` (`nnz=1638`) no empty rows occurred in either trial, so the defect is specific to the size-override path.

### F10 — Out-of-range coordinates: heap-buffer-overflow in the oracle [D] — from the degenerate probe

- **Mechanism.** `matrix[element.row][element.column] = element.value;` indexes without a bounds test.
- **Reproducing input.** A triplet with `row ≥ N` or `column ≥ N`.
- **Expected.** Rejection or a documented precondition.
- **Oracle result.** ASan reports a heap-buffer-overflow read and write inside the materialisation loop.
- **Driver behaviour.** Not reachable from the driver's own generator (`fillRand(A_rows, 0UL, N)` yields `rand() % N`, i.e. `[0, N-1]`), so this is a latent robustness defect of the oracle rather than a live pipeline failure.
- **Location.** `baseline.hpp:22`.
- **Falsification attempt.** Confirmed the generator's range arithmetic to establish non-reachability; reported anyway per the completeness instruction.

### F11 — On near-singular systems the answer is pivoting-strategy dependent [D] — from the degenerate probe

- **Mechanism.** The oracle uses partial pivoting; an independently correct complete-pivoting solve of the same matrix diverges by O(10) while both residuals stay small. At such conditioning the "correct answer" is not determined to 1e-3 by the mathematics.
- **Reproducing input.** Driver-generated near-singular instances; the verifier's finite-garbage instance at `N=32` (`max|x| = 5.32e16`).
- **Expected.** Either a well-conditioned generator or a conditioning-aware tolerance.
- **Oracle result.** A finite vector that is imposed on submissions as a hard absolute 1e-3 requirement.
- **Driver behaviour.** Grades with a fixed absolute epsilon regardless of conditioning.
- **Location.** `baseline.hpp:29-58` versus `cpu.cc:123`.
- **Falsification attempt.** Checked that both solvers are individually correct (small residuals) — they are; the divergence is genuine ill-conditioning, not a solver bug.

### F12 — Back-substitution loop counter is `int` while `N` is `size_t` [D] — from the degenerate probe

- **Mechanism.** `for (int i = N - 1; i >= 0; --i)` at `baseline.hpp:61`. For `N = 0` the value `N - 1` is `SIZE_MAX`, whose conversion to `int` is implementation-defined; the loop also cannot address `N > INT_MAX`.
- **Reproducing input.** `N = 0`.
- **Expected.** A no-op at `N = 0`.
- **Oracle result.** Correct in practice on this platform (the conversion yields −1), i.e. the defect is latent.
- **Driver behaviour.** `N = 0` is reachable via the size override.
- **Location.** `baseline.hpp:61`.
- **Falsification attempt.** Verified the observed behaviour is benign here; reported as a portability defect, not a live failure.

### F13 — The prompt does not specify duplicate handling, and its example cannot teach it [B] — verified

- **Mechanism.** The prompt says only "A is a sparse NxN matrix in COO format" and gives one duplicate-free example. Nothing states the overwrite rule the oracle enforces, and the standard convention in the surrounding ecosystem (SciPy, MATLAB) is accumulation — which is also the rule the driver's own `b` construction uses.
- **Reproducing input.** The prompt text and example themselves (`thesis/prompts/generation-prompts-thesis.json`, all three parallelism entries; the same comment block is mirrored at `baseline.hpp:9-15` and `cpu.cc:7-13`).
- **Expected.** A model reading this prompt implements accumulation, or picks either convention with no guidance.
- **Oracle result.** Only the overwrite convention passes.
- **Driver behaviour.** Grades the undocumented convention as the only correct one.
- **Location.** prompt entries plus `baseline.hpp:9-15`.
- **Falsification attempt.** Checked whether the example could disambiguate: it is duplicate-free, so it is provably incapable of doing so. The verifier tried the reading "B means the oracle's convention is plausible" and rejected it: the driver's own `b` rule fixes the intended semantics, so this is underspecification *plus* a contradicted specification, not a free choice.

### F14 — At small sizes the posed system is strictly inconsistent: no solution exists [F] — completeness critic

- **Mechanism.** The pooled premise "b = A·x_gen, so a solution always exists" holds only in exact arithmetic. `cpu.cc:60` accumulates in `double`, so `b = A·x_gen + δ` with `‖δ‖_∞ ≈ 1e-15`. When `A` is exactly rank-deficient — the norm at every size the override reaches — its left null space is non-trivial and a generic `δ` is not orthogonal to it, so `b ∉ range(A)`.
- **Reproducing input.** Minimal, entirely by the driver's own rule: `N=2`, `A = [{0,0,3.0},{1,0,7.0}]`, `x_gen = [0.1, 0.0]` → `b = [0.30000000000000004, 0.70000000000000007]`. Certificate `y = (7,−3)`: `7·b₀ − 3·b₁ = 1/9007199254740992 ≠ 0`.
- **Expected.** "No solution" — the task as posed is unsatisfiable.
- **Oracle result.** `[-nan, inf]`. On instance `inst_16_1`: rank 11/16, five left-null certificates, all with `yᵀb ≠ 0` (`yᵀb = −8.74e-16`) while `yᵀ(A·x_gen) = 0` exactly.
- **Driver behaviour.** Exact classification over **Q** of 20 consecutive driver instances per size:

  | TEST_SIZE | inconsistent | underdetermined | unique | mean exact rank |
  |---|---|---|---|---|
  | 8 | 13/20 | 7 | 0 | 3.6/8 |
  | 16 | 17/20 | 3 | 0 | 11.3/16 |
  | 24 | 18/20 | 2 | 0 | 20.1/24 |
  | 32 | 10/20 | 9 | 1 | 29.8/32 |
  | 40 | 10/20 | 7 | 3 | 38.5/40 |
  | 48 | 7/20 | 8 | 5 | 47.2/48 |

- **Location.** `cpu.cc:58-61` (double accumulation) with `cpu.cc:99-104` (sizing).
- **Falsification attempt.** Verified the replica against the real driver (the critic's trial-0 reference value `x[0] = -5.3908181533493105` matches the value the real driver prints). Checked the alternative explanation "underdetermined, so pick any solution": refuted by the explicit left-null certificates — on the majority of these instances there is nothing to pick.

### F15 — `ENHANCED_FILL` is inert at benchmark 45 only [F] — completeness critic

- **Mechanism.** `cpu.cc:99` honours `ENHANCED_TEST_SIZE_DEFAULT(128)`, but `validate()` draws its inputs through `createRandomLinearSystem`, whose fills are bare `fillRand` (`cpu.cc:44-46`, `:56`). `ENHANCED_FILL` never appears in the file. 50 of 60 `cpu.cc` drivers use it, including all four sparse_la siblings at the analogous place.
- **Reproducing input.** The same driver built with fill patterns NONE / all_zeros / all_same / ascending / extreme_values.
- **Expected.** Different inputs per pattern.
- **Oracle result.** Identical input hash `14995923497376398080` in all five (`A₀={0,10,9.2431002106718267}`, `b₀=149.53985314767527`), while `-DENHANCED_TEST_SIZE=16` *did* take effect. Control on benchmark 47: each pattern produces a different hash.
- **Driver behaviour.** Half the enhanced-tests mechanism works here, half is a silent no-op.
- **Location.** `cpu.cc:44-46`, `:56`, `:99`.
- **Falsification attempt.** Cross-checked against a sibling benchmark to show the mechanism itself works. (Whether specs exist that rely on it could not be checked — `thesis/results/` is outside the read allowance.)

### F16 — Size mismatch aborts the process; with `-DNDEBUG` it silently passes [E] — completeness critic

- **Mechanism.** `utilities.hpp:270` begins with `assert(a.size() == b.size());`, and no shipped `CXXFLAGS` sets `-DNDEBUG` (checked in `drivers/build-configs.json` and at runtime).
- **Reproducing input.** A correct submission that finishes with `x.push_back(...)` on the pre-sized `x_test` instead of assigning into it. The prompt never states that `x` arrives pre-sized to `N`.
- **Expected.** A verdict — pass or fail — not process death.
- **Oracle result.** `Assertion 'a.size() == b.size()' failed. Aborted (core dumped)`, exit 134, **no `Validation:` line at all**. Built with `-DNDEBUG` it is worse in kind: `reportAndCompare({1,2,3},{1,2,3,4},1e-3)` returns **PASS**.
- **Driver behaviour.** The control submission, identical but using `assign`, passes.
- **Location.** `drivers/cpp/utilities.hpp:270`.
- **Falsification attempt.** Verified the `NDEBUG` state from the built binary rather than assuming it.

### F17 — Identifier collision with the driver [F] — completeness critic

- **Mechanism.** `cpu.cc:23` includes the model's code, then `cpu.cc:35` defines `void sortCOOElements(std::vector<COOElement>&)` at namespace scope — the most natural helper name for this task.
- **Reproducing input.** A submission that defines a helper of the same name.
- **Expected.** Compilation.
- **Oracle result.** `cpu.cc:35:6: error: redefinition of 'void sortCOOElements(std::vector<COOElement>&)'`.
- **Driver behaviour.** Scored as a build failure, i.e. as if the model produced no answer.
- **Location.** `cpu.cc:23` and `:35`.
- **Falsification attempt.** Confirmed the include order is what makes the model's definition first.

### F18 — The CUDA and Kokkos drivers are a different benchmark [F] — completeness critic

- **Mechanism.** `gpu.cu:94` and `kokkos.cc:104` hard-code `const size_t TEST_SIZE = 128;` (ignoring the override); `gpu.cu:42-44` / `kokkos.cc:48-50` draw triplets interleaved while `cpu.cc:44-46` draws them in three batches, so the same RNG stream yields different matrices; `gpu.cu:127` / `kokkos.cc:139` verify with `fequal` (no MISMATCH diagnostics).
- **Expected.** One benchmark definition per benchmark.
- **Oracle result.** Three mutually inconsistent instantiations of "the same" task.
- **Driver behaviour.** **Scope caveat:** the prompt file holds exactly 180 entries (60 serial + 60 omp + 60 mpi, no cuda/hip/kokkos), so these paths are dead in this thesis and could not be executed (no nvcc, no Kokkos).
- **Location.** `gpu.cu:42-44,94,127`; `kokkos.cc:48-50,104,139`.
- **Falsification attempt.** Established the paths are unused before reporting, and labelled the finding accordingly.

### F19 — The shipped `mpi+omp` configuration does not compile [F] — completeness critic

- **Mechanism.** `utilities.hpp:35-45` is a single `#if/#elif` chain; with `USE_MPI_OMP` the `omp.h` branch wins and `#include <mpi.h>` is unreachable, while `GET_RANK` (`:118`) is still expanded unconditionally inside `mismatchIsRoot()` (`:264`).
- **Reproducing input.** Building any benchmark with the `mpi+omp` configuration from `drivers/build-configs.json`.
- **Expected.** A working build — the configuration is shipped, listed in `problem-sizes.json`, and advertised at `cpu.cc:1`.
- **Oracle result.** `utilities.hpp:118:38: error: 'MPI_COMM_WORLD' was not declared in this scope` (and `MPI_Comm_rank`). Reproduced on benchmark 47 as well (13 errors) — this is utilities-level and affects all benchmarks.
- **Driver behaviour.** The other three configurations build and run: serial PASS, omp PASS (4 threads), mpi PASS at np = 1, 2, 4.
- **Location.** `drivers/cpp/utilities.hpp:35-45`, `:118`, `:264`.
- **Falsification attempt.** Reproduced on a second benchmark to exclude a benchmark-specific cause.

### F20 — The generated matrix has an ~90% empty diagonal [F] — completeness critic

- **Mechanism.** With uniform random coordinates at density 0.1, the expected fraction of occupied diagonal entries is `1 − e^{−0.1} = 0.0952`.
- **Reproducing input.** Driver-generated instances at `N = 32…256`.
- **Expected.** For the omp and mpi prompts, which invite parallel solution methods, a matrix on which such methods are applicable.
- **Oracle result.** Measured diagonal occupancy 0.0918–0.0975; at `N=128`, 12.4 of 128 diagonal entries nonzero over 300 instances.
- **Driver behaviour.** Jacobi, Gauss-Seidel/SOR and diagonally preconditioned CG — the natural parallel methods — are inapplicable by construction, so the task effectively admits only direct elimination.
- **Location.** `cpu.cc:41-53` (`createRandomLinearSystem`) with `utilities.hpp:29-32`.
- **Falsification attempt.** Compared the measured occupancy against the closed-form prediction to exclude a sampling artifact.

---

## Classification

| # | finding | class |
|---|---|---|
| F1 | duplicate COO: oracle overwrites, driver accumulates | **C** |
| F2 | graded reference depends on unspecified tie order | **F** |
| F3 | explicit zero triplet deletes an entry | **C** |
| F4 | duplicate pair summing to zero | **F** |
| F5 | no singularity guard, silent NaN/Inf | **D** |
| F6 | validator counts NaN as equal | **F** |
| F7 | F5+F6 compose into vacuous validation | **F** |
| F8 | generating ground truth destroyed, oracle used as reference | **F** |
| F9 | `nnz < N` below size 10: singular by construction | **F** |
| F10 | out-of-range coordinates: heap-buffer-overflow | **D** |
| F11 | near-singular: answer is pivoting-strategy dependent | **D** |
| F12 | `int` loop counter against `size_t N` | **D** |
| F13 | prompt silent on duplicates, example cannot disambiguate | **B** |
| F14 | posed system strictly inconsistent at small sizes | **F** |
| F15 | `ENHANCED_FILL` inert at this benchmark only | **F** |
| F16 | size mismatch aborts; with `-DNDEBUG` silently passes | **E** |
| F17 | `sortCOOElements` identifier collision | **F** |
| F18 | CUDA/Kokkos drivers are a different benchmark | **F** |
| F19 | shipped `mpi+omp` configuration does not compile | **F** |
| F20 | ~90% empty diagonal defeats parallel methods | **F** |

Totals: **C ×2, D ×4, E ×1, F ×12, B ×1.** No finding classified **A**; the only clean result is the negative one recorded under *Test cases* (correct arithmetic and a correctly reproduced documented example on well-posed duplicate-free input).

Adversarial verification: 14 findings verified independently, **14 CONFIRMED, 0 REFUTED, 0 reclassified**. Verifiers corrected four peripheral details, all incorporated above: the optimisation-level clause in F2 (dropped), the reachability of F3 through enhanced fill patterns (removed — see F15), the size bound in F7 (≤33 rather than ≤32, plus the NaN case at the default size), and the duplicate-pass count in a supporting figure.

---

## Confidence and blind spots

### Would I release this benchmark for a full run?

**No.** Clear NO-GO, on three independent grounds, each sufficient on its own:

1. **The graded reference is wrong on the inputs the benchmark itself generates** (F1): at the default validation size the oracle's answer misses the generating solution by up to 184 on components bounded by 10, and a mathematically correct standard-COO submission is scored FAIL while a submission reproducing the oracle's convention is scored PASS. Any pass rate from this benchmark measures convention-matching, not solving.
2. **The graded reference is not even well-defined** (F2, F14): it depends on unspecified sort tie order, and at most sizes reachable through the size override the posed system has no solution at all.
3. **Validation is vacuous in exactly the regime where the oracle breaks** (F5–F7, F9): a candidate that ignores its inputs and returns NaN passes at the default size.

A repair is not a one-line change: F1 fixes the convention, but F14 shows that "return a solution" is unsatisfiable at small sizes, so the benchmark also needs a specified least-squares or minimum-residual convention — which exists nowhere in prompt, docstring or driver — or a generator that guarantees solvable, better-conditioned instances.

### Which error class could this method still miss?

- **A globally consistent but misnamed operation** — see the explicit question below.
- **Statistical or seed-dependent effects**: everything was measured on the deterministic unseeded `rand()` stream and a few dozen instances per size; a defect that appears only for other seeds or much larger `N` would not show.
- **Parallel-path-specific semantics at scale**: the omp and mpi builds were exercised only at small rank/thread counts (np = 1, 2, 4). Race conditions or rank-dependent divergence in the *driver* would not be caught.
- **Performance-path defects**: `compute()`/`best()` and the timing harness were not audited — only the correctness path.
- **Toolchain-dependent behaviour**: everything ran under one image (GCC 13.3). A defect visible only under another compiler or optimisation level would be missed — indeed, one verifier could not reproduce an optimisation-level claim that a probe had made.

### Did I read anything from the blocklist?

**Yes — and the blindness premise is broken for me, the orchestrating agent, in a way that no disclosure can repair.** Earlier tasks in this same session (before this brief existed) analysed `pilot_001` records, `overview.md/csv`, prior audit reports and git history covering this exact benchmark. I therefore began this task already knowing the duplicate-COO convention conflict and the NaN-blind comparator. That knowledge predates the first line of this investigation; the "point in the investigation" is *before it started*.

Mitigation, stated so the calibration keeps whatever value it can:

- Every number in this report was produced by execution during this task — my four probes and the agents' — not quoted from any earlier document. The exact-integer, representation-variant, scale, tie-order and truth-table experiments were designed and run here.
- The five probe agents and the 14 verifiers started with **no session context**. They are genuinely blind, and they derived F1 independently from `baseline.hpp:22` next to `cpu.cc:60` — as their own contamination reports state.
- **However**, I wrote their task prompts. I did not name a convention, a mechanism or a finding, and I did not mention duplicates, NaN, or singularity in the four probe briefs' *conclusions* — but I did choose the probe axes ("do different valid representations give different results?", "degenerate domain", "what does the driver actually pose?"). Choosing where to look is a weaker hint than naming the answer, but it is not nothing. Findings F14–F20 came from the completeness critic, whose brief deliberately did **not** name the gaps, and are the least contaminated part of this report; F10, F11, F12, F16, F17, F19 were likewise nowhere in my prior knowledge.

Agent-side disclosures, reported by the agents themselves:

- **All five** received an automatic `gitStatus` block in their environment preamble, before acting: branch name `thesis-static-analysis`, main branch `develop`, five recent commit subjects (one reads "Phase 0: prompt-vs-oracle consistency check + corrected pilot numbers"), and three untracked *filenames* under blocklisted directories. Branch names and commit messages are on the blocklist. Contents were never opened; no benchmark, finding or convention is named there.
- **One incident** (driver-semantics probe): early on, before any execution or finding, it ran a recursive `grep` from the repo root whose *traversal* included blocklisted directories. Output was pre-filtered with `grep -v "thesis/docs\|thesis/results"`, the command exceeded its timeout and was backgrounded, the agent never read the output and explicitly stopped the background task so no completion notification could deliver it. Zero bytes of blocklisted content entered its context. It also ran `ls thesis` (directory names only).
- **One deliberate narrow read** (representation probe): a name-scoped `grep` over non-blocklisted directories to find `DRIVER_PROBLEM_SIZE`, then lines 400–420 of `drivers/problem-sizes.json`. It explicitly did **not** open `drivers/test-serial-outputs.json`, which could have contained expected outputs.
- **One aggregate read** (critic): histogram of `parallelism_model` over the allowed prompt file (180 entries) to scope F18/F19; no other benchmark's prompt text read.

### Which finding came from method step 9 (different representations of the same input)?

**From step 9: F1, F2, F3, F4** — the four representation-dependence findings. The decisive experiment was T6a–T6e: one mathematical matrix in five valid COO encodings yielding five different oracle answers.

**Would have been found without step 9: F5, F6, F7, F8, F9, F10, F11, F12, F14, F15, F16, F17, F19, F20** — degenerate-domain probing, the validator truth table, the driver-semantics trace and the critic's gap probes are all independent of the representation question. F13 depends on F1 having been established (it is the statement that the prompt cannot teach the oracle's convention), and F18 came from cross-checking sibling drivers.

Note the asymmetry: **step 9 found the finding that decides the GO/NO-GO** (F1), while the other steps found more findings but none that alone invalidates the benchmark's headline semantics — except F14, which the completeness critic found by exactly adjudicating the *driver-generated* instances that everyone else had only reasoned about.

### Which error classes did this investigation actually test — and which not?

**Tested:**

1. *Wrong result on exactly known ground truth* (integer systems with `b = Ax` computed exactly) — the oracle passed this.
2. *Internal inconsistency between artifacts* — driver's `b` rule versus oracle's matrix materialisation. This is what found F1.
3. *Representation dependence* — permutation, duplicates, explicit zeros.
4. *Domain and degeneracy* — singularity, empty input, size overrides, out-of-range indices, UB under sanitizers.
5. *Validator behaviour* — NaN/Inf truth table, tolerance semantics, size-mismatch handling.
6. *End-to-end verdict behaviour* — real driver against hand-written submissions of each convention.

**Not tested:** performance path; MPI/OpenMP at scale; other seeds and much larger `N`; other toolchains; CUDA/Kokkos paths (dead in this thesis, and not runnable here); and whether any enhanced-test spec depends on the inert `ENHANCED_FILL` (outside the read allowance).

**The explicit question — would this method have caught an oracle that computes consistently and crash-free, but a *different operation* than its name and prompt claim, with a documented example that matches it?**

**No — not reliably, and I would expect it to return "consistent".** The two levers that worked here would both be silent in that scenario:

- The *internal-inconsistency* lever (F1) fires only because two artifacts disagree. If prompt, example, driver and oracle all consistently implement the same non-standard operation, every cross-check agrees and nothing fires.
- The *exact-ground-truth* lever fires only if the auditor derives the expected value from the **mathematical definition of the named operation** rather than from the documented example. Here that worked because "solve `Ax=b`" pins the answer uniquely once the COO convention is fixed — and the convention was pinned by the driver, not by me. Where the operation is convention-laden (sign of a Fourier exponent, tie-breaking in a sort, orientation of a convex hull), an auditor who takes the documented example as the expected value will confirm the oracle and report "consistent".

So this calibration covers the classes *(i) internal inconsistency between prompt/driver/oracle*, *(ii) wrong on exactly-known ground truth*, *(iii) domain and degeneracy*, *(iv) validator blindness*, and *(v) representation dependence*. It does **not** cover *(vi) a globally consistent operation that is misnamed by its prompt*. Catching (vi) requires a different instrument: deriving the expected values from an independent authoritative definition of the named operation and refusing to use the documented example as ground truth — precisely the step this method takes only in the exact-integer test, and only because the task name happened to determine the answer.

---

*All analysis scripts, probe binaries and raw outputs live in the session scratchpad under `oracle45/` and are referenced by name above; they are audit artifacts, not part of the repository. This report is the only file created in the repository.*

---

## Status as of Domain Approval Wave — 2026-08-25 — based on fb40fc893d347feb6df62e05b019a5577067fa79

Append-only status section; the text above is historical evidence and is unchanged.

- **Confirmed:** the random COO construction's core defects stand. In particular, at tiny N the current generator produces an EMPTY COO list (N*N*0.1 < 1 for N <= 3) and therefore a singular system — re-measured in this wave through the real driver/build path (F5b-style baseline-vs-baseline: `baseline_incompatible` at N in 1..3 for every fill pattern; the pattern axis is inert here, `fill_sites = 0` in benchmark_shapes.json).
- **Superseded (by the D4 numeric gate, now closed):** the open questions "gamma, row-scale bound, value lattice" are frozen. Construction: square, duplicate-free integer COO with guaranteed diagonal; off-diagonals in ±[1..4]; per-row entries max(2, round(0.1·N)) incl. diagonal; dominance |a_ii| = S_i + ceil(S_i/4) (floor 1), i.e. |a_ii| >= 1.25·S_i (gamma = 1.25, multiplicative); x_gen integer in [-8,8]; b = A·x_gen exact.
- **New evidence (proof-by-execution, 3 scales x 5 deterministic fill variants):** max|A_ij| = 760, max|A_ij·x_j| = 6080, max over EVERY partial row sum = 10944, max|b_i| = 10944 — all < 2^53 with >= 8.23e11x headroom; 0 duplicates, 0 missing diagonals, min dominance margin 3; Varah cond_inf bound <= 16.80; real `correctSolveLinearSystem` finite in all 15 runs and recovers x_gen to max|diff| <= 2.03e-13 (validation tolerance 1e-3); oracle runtime at L=1536: 1.15–1.45 s median-of-3.
- **Still open (queued, NOT this wave):** replacing the random generator with the frozen construction (generator wave), the duplicate-free prompt statement (prompt wave), and the unstable-`std::sort`-tie diagnosis of the graded reference for the CURRENT random construction remains valid until that generator lands.
