# Wave 2A — Domain-Critical Benchmark / Oracle / Generator Implementation Report

Date: 2026-08-26 · Branch: `thesis-static-analysis` · Base commit: `d968771a4d1eeccce99fe7d4936cbb395ef107c8`

This wave implements the ALREADY FROZEN domain/numeric contracts of the
Domain Approval Wave in the productive benchmark, oracle, validator and
input-construction code. It takes **no new domain, prompt, timing or
enhanced-pattern decision**. No prompts changed, no enhanced specs
regenerated, no pilot_002, no full run, no commit, no `git add`.

---

## 1. Repository state

```
git branch --show-current   thesis-static-analysis
git rev-parse HEAD          d968771a4d1eeccce99fe7d4936cbb395ef107c8   (= expected; parent fb40fc8…)
git status --porcelain (before any change): empty (clean)
git diff --stat / --cached --stat (before): empty
```

The HEAD commit `documentation` contains only the Domain-Approval-Wave
documents plus the `.gitignore` change — no productive code moved since the
Domain Approval Wave, so no frozen contract premise changed (A0 preflight
gate: open).

## 2. Source documents / frozen contracts read

Read in full before any change: `thesis/docs/benchmark-domain-table.json`
(top level + the 12 affected rows in full), `domain-table-approval-report.md`
(§4, §5, §11–14, §17, §20–26), `oracle-audit-calibration-45.md` (findings +
append-only status), `oracle-correctness-audit.md` (BL-13…BL-21 + status
section), `fft-family-consistency.md` (status section; no FFT work in this
wave), `thesis/evaluation/wave1_final_gate_report.md` (transport/consumer
inventory, F1–F7), `thesis/enhanced_tests/benchmark_shapes.json`, plus the
CURRENT code of all affected `cpu.cc`/`baseline.hpp`, `utilities.hpp`,
`harness-markers.hpp`, `enhanced-fill.hpp`, the model drivers,
`patch_drivers.py` (one-shot patcher: files already carrying
`ENHANCED_TEST_SIZE_DEFAULT` are skipped — edits are build-stable) and
`derive_shapes.py` (writes ONLY `benchmark_shapes.json`).

Every parameter needed for implementation was uniquely reconstructable from
the frozen documents — **no `BLOCKED — FROZEN CONTRACT DETAIL NOT FOUND`**
case occurred for any implemented part (the one deliberate QUEUED case is
A2.4, §7).

## 3. Files changed

12 productive files + 1 regenerated metadata artifact (§26b, §27 for the
list). All under `drivers/cpp/benchmarks/` except the regenerated
`thesis/enhanced_tests/benchmark_shapes.json`. No prompt file, nothing under
`thesis/results/`, no spec/cache/hash artifact, no Python production code.

## 4. A0 preflight table

| Benchmark | Current defect (before) | Frozen target | Files changed |
|---|---|---|---|
| sparse_la/45 | random COO: duplicates every trial, singular below N~96, near-singular 3–6%, NaN-prone oracle as sole truth; global `sortCOOElements` collision (F17) | D4 construction: duplicate-free dominant integer COO, gamma 1.25, lattice ±[1..4], x_gen ∈ ℤ∩[-8,8], b=A·x_gen exact; grade vs x_gen | `45_…/cpu.cc` |
| sparse_la/49 | random COO: ~90% zero diagonal → unpivoted Doolittle NaN in ~100% of trials (BL-16/17/21); global `sortCOO`/`isCOOEqual` | D5 construction: known band-k(N) L/U ground truth, pivots 2^e (e∈[0,5]), lattice ±[1..4], A=L·U exact, duplicate-free; bit-exact reference recovery | `49_…/cpu.cc` |
| sparse_la/46 | duplicate coordinates every trial (BL-13/20); ENHANCED_FILL drives indices out of range into the unguarded oracle (BL-14); square-only validation | unique (row,column), valid indices, no silent skip, nonsquare case (I13) | `46_…/cpu.cc` |
| sparse_la/47 | duplicate coordinates every trial; index sites pattern-driven out of range (oracle guard absorbs, candidate would not) | unique (row,column), valid indices | `47_…/cpu.cc` |
| sparse_la/48 | duplicate indices every trial (BL-15); patterns 5/6/9 → OOB heap write in the oracle | unique indices per vector, valid range, result-length check | `48_…/cpu.cc` |
| reduce/26 | absolute scalar epsilon 1e-4 (vacuous/unsatisfiable across the magnitude range; BL-09) | frozen D6/I8 verdict rules A–E, eps_rel = 8·n·u, no absolute floor | `26_…/cpu.cc` |
| search/38 | try i==1 writes `x[0..19]` unconditionally → heap overflow for TEST_SIZE < 20 | size-safe overwrite; semantics unchanged; `numTries = 10` NOT touched (queued) | `38_…/cpu.cc` |
| sort/41 | `k = rand() % n` ∈ [0,n-1] vs 1-indexed oracle `x_copy[k-1]` (k=0 → UB; k=n unreachable); n=0 → modulo-zero | k ∈ [1,n]; explicit n=0 harness guard | `41_…/cpu.cc` |
| transform/59 | oracle calls the CANDIDATE's `isPowerOfTwo` (candidate-dependent oracle, fix REQUIRED) | independent trusted predicate in `pareval_harness` | `59_…/baseline.hpp` |
| graph/19 | validate() never zeroes A between attempts → graph accumulates to ~K_N (issue #77) | per-attempt zero reset; family semantics unchanged | `19_…/cpu.cc` |
| dense_la/02 | validation square-only; a square-assumption candidate passes | deterministic nonsquare case (M, K=M/4, N=M/2) | `02_…/cpu.cc` |
| dense_la/04 | validation square-only | deterministic nonsquare case (M=N/2) | `04_…/cpu.cc` |

## 5. Sparse shared coordinate/index contract (A1)

* **45/46/47/49:** at most one entry per `(row, column)` — the validation
  generators now draw coordinates **directly unique** (rejection sampling of
  distinct cells / the constructive D4/D5 emitters, which are unique by
  construction). No post-hoc dedupe: target nnz, value distribution and
  structure are exactly as declared (46/47: nnz = floor(0.1·R·C) distinct
  cells; 45: per-row distinct columns; 49: the deterministic band cell set).
* **48:** at most one entry per index within each sparse vector (distinct
  draws from [0,N)); x and y may still share indices — the merge case, not a
  duplicate.
* **Valid indices:** by construction in every generator (cells drawn inside
  the declared dimensions). Additional NDEBUG-proof tripwires in the trusted
  validation paths of 45/46/47/48/49: if harness input ever violated
  uniqueness bounds/ranges, the trial emits the EXISTING
  baseline-incompatibility marker and is skipped — no OOB into the unguarded
  oracles (46: `Y[a.row*N+x.column]`, 48: `z[index]`), **no silent
  `continue` without a marker, no candidate FAIL for invalid harness input**,
  no new verdict class (frozen Wave-1 transport reused verbatim:
  `mismatchNoteNonFiniteReference()`; the Python classifier keys on the
  authenticated marker line, not the reason substring).
* **Helper collision safety:** every new namespace-level helper lives in
  `namespace pareval_harness`. The pre-existing collision-risk globals in
  the touched files were moved there as well: `sortCOOElements` (45, 46 —
  the pilot's F17 redefinition class), `sortCOO`/`isCOOEqual` (49). Grep
  audit: no global `sortCOOElements`/`sortCOO`/`isCOOEqual` remains in any
  thesis-relevant `cpu.cc` (remaining hits only in the thesis-dead
  `gpu.cu`/`kokkos.cc` paths).

## 6. sparse45 core implementation (A2)

* **Exact frozen parameters used (D4, verbatim from the domain table):**
  per-row entries `max(2, round(SPARSE_LA_SPARSITY·N))` incl. diagonal
  (capped at N — a duplicate-free row holds at most N columns; the cap is
  the arithmetic consequence of the frozen duplicate-free + diagonal
  invariants at tiny N, not a new decision); off-diagonal lattice integers
  |a_ij| ∈ [1,4], sign free; `|a_ii| = S_i + g_i`, `g_i = ceil(S_i/4)`
  floor 1 (⇔ gamma = 1.25 multiplicative), diagonal sign free; x_gen ∈
  ℤ∩[-8,8]; b = A·x_gen accumulated in `long long` — exact.
* **Construction path:** `pareval_harness::buildDominantSystem` (validation
  only; the timed `createRandomLinearSystem` path is untouched, §26).
  Deterministic unseeded-rand draws, identical on every MPI rank, BCAST
  convention kept.
* **x_gen independence:** the candidate is graded against x_gen — never
  against a numerically solved result. The real `correctSolveLinearSystem`
  still runs once per trial as a harness SANITY CHECK only (non-finite
  reference → existing BI transport, trial skipped, never a candidate
  verdict). Runtime enforcement beyond non-finiteness was deliberately NOT
  added — the frozen verdict vocabulary defines no branch for a
  finite-but-deviating selftest, and the accuracy property is proven by A9
  instead (recovery ≤ 4.5e-14, §18/§24).
* **b = A·x_gen:** exact (every operand/product/partial row sum an integer
  < 2^53; independently re-verified, §18).
* **Exactness preservation:** `if`-based tripwires (≥2^53 partial-sum bound,
  construction feasibility) — plain branches, never `assert`, so `-DNDEBUG`
  cannot remove them (proven by the NDEBUG runs, §21).
* **Candidate comparison semantics:** unchanged — `reportAndCompare(x_gen,
  x_test, 1e-3)` (the existing role-aware comparator, existing tolerance).
* **A2 core status: IMPLEMENTED.**

## 6a. sparse45 tolerance-gap audit (A2.3b)

| Quantity | Value | Metric |
|---|---|---|
| accepted candidate tolerance | `1e-3` (cpu.cc, unchanged) | per-element ABSOLUTE: an index is flagged iff \|expected−got\| > 1e-3 (⇒ acceptance bound = max-abs elementwise) |
| observed reference/x_gen recovery error under D4 (Wave-2A, real path) | 4.441e-14 (L=1536), 3.375e-14 (M=512), 1.421e-14 (S=128) | max-abs elementwise (same metric) |
| frozen D4 evidence | ≤ 2.03e-13 | max-abs elementwise |
| conditioning evidence | Varah cond_inf ≤ 16.80 (frozen, N-independent) | — |
| tolerance gap (metrics comparable: both max-abs elementwise) | **1e-3 / 4.441e-14 ≈ 2.3e10 (≈ 10 orders of magnitude)** | — |

The accepted candidate tolerance is ~10 orders of magnitude looser than the
error the constructive, well-conditioned D4 domain admits. **Wave 2A did NOT
change the tolerance** (frozen: no new candidate-tolerance value exists in
the approval documents; inventing or tightening one is forbidden here).
→ **`QUEUED DECISION — sparse45 candidate tolerance vs. constructive
conditioning`** (§29). A2 core remains IMPLEMENTED.

### A2.3c negative-test interpretation

The A9.2 result "wrong solution FAILs" proves basic discrimination only, NOT
numerical sharpness of the tolerance. Additionally executed synthetic
boundary probes against the EXISTING tolerance: uniform error +5e-4 (inside
1e-3) → PASS as expected; +2e-3 (outside) → FAIL as expected (§19). No new
tolerance was derived from this.

## 7. sparse45 EnhancedFill / pattern mapping (A2.4)

* **What the frozen documents specify:** the D4 gate freezes the INVARIANT
  ("value patterns may later vary off-diagonal signs/magnitudes within the
  lattice and x_gen within [-8,8] without leaving the proven envelope",
  `enhanced_fill_invariant`) — NOT a concrete mapping of global pattern
  names. Row 45's `fill_effect_note` and the approval report §23–26
  explicitly queue "adversarial fill-pattern policy" and "input-variation
  policy" to the later ENHANCED wave.
* **Patterns that currently exist** (enhanced-fill.hpp): random, all_zeros,
  all_same, ascending, descending, alternating, extreme_values,
  duplicate_at(k), sorted_except_one(k), spike_at(k), explicit_values.
* **Concrete mapping:** none is frozen. Benchmark 45's validate() has no
  ENHANCED_FILL site (before and after this wave: `fill_sites = 0`), and no
  pattern semantics was invented, capped, ignored or reinterpreted here.
* **Status: `A2.4 = QUEUED — FROZEN CONTRACT DETAIL NOT FOUND (sparse45
  EnhancedFill pattern mapping)`** — the source-of-truth documents mark the
  mapping as later enhanced-pattern policy, so per A11.2 this QUEUED does
  not block the wave. The current state is NOT reported as
  `FILL_EFFECT_VERIFIED` anywhere.

## 8. sparse49 implementation (A3)

* **Exact frozen k policy:** `k(N) = max(1, round((SPARSE_LA_SPARSITY·N −
  1)/2))`, k = half-bandwidth (entries |i−j| ≤ k); measured k = 1/6/51 at
  16/128/1024 — matches the frozen evidence exactly. Fixed k was NOT
  reintroduced.
* **Lattice / pivot contract:** L unit-lower, band-k, off-diagonals
  ±[1..4]; U upper, band-k, off-diagonals ±[1..4], diagonal 2^e with
  e ∈ [0,5] (min pivot 1; every division exact).
* **L/U ground truth:** the constructed factors ARE the graded expected
  result (candidate compared against `L_true`/`U_true`), independent of any
  numeric factorization. A = L·U computed exactly in integers and emitted as
  the duplicate-free COO of ALL band cells (nnz = N(2k+1) − k(k+1):
  46/1622/102820 at S/M/L; density 0.180/0.099/0.098 — the frozen ~0.1
  family density preserved). No `x_gen` (forbidden for 49).
* **Real Doolittle selftest:** `correctLuFactorize` (its REAL evaluation
  order, untouched) runs once per trial; on the D5 construction it recovers
  L/U **bit-exactly** (0 mismatches over 3·N² entries at each of S/M/L ×
  3 reps, §18) — the runtime branch enforces the frozen non-finite rule
  (BI transport) only, exactness is proven by test, not demanded of
  candidates.
* **Candidate comparison semantics:** unchanged `reportAndCompare(…, 1e-3)`
  on both factors — NOT switched to bit-exact.
* **Fill behavior (A3.4):** the D5 construction varies factor values within
  the frozen lattice via the deterministic rand() stream. The old
  ENHANCED_FILL index/value sites are gone (structural construction); a
  concrete pattern-name mapping onto factor construction is NOT frozen
  anywhere → **`QUEUED FOR ENHANCED PATTERN-POLICY WAVE`** (same gap class
  as 45). No specs regenerated.
* **A3 status: IMPLEMENTED.**

## 8a. sparse49 tolerance-gap audit (A3.5)

| Quantity | Value | Metric |
|---|---|---|
| candidate comparison rule | `reportAndCompare(L_true, L_test, 1e-3)` ∧ same for U (unchanged) | per-element ABSOLUTE 1e-3 on both factors |
| trusted recovery precision (real Doolittle on D5 input) | **exactly 0** — bit-exact, 0/3·N² mismatches at 16/128/1024, 0 non-finite | max-abs elementwise (same metric) |
| tolerance gap | **not finitely expressible** (1e-3 / 0): the reference path achieves EXACTNESS, the acceptance bound is 1e-3 — many orders of magnitude looser than achievable | — |

**Wave 2A did NOT change the tolerance.** → **`QUEUED DECISION — sparse49
candidate tolerance vs. constructive conditioning`**. Not inferred from the
bit-exact selftest that candidates must be bit-exact. A3 remains IMPLEMENTED.

## 9. sparse46/47/48 changes (A4)

* **46 (SpMM):** unique `(row,column)` per operand (distinct-cell draw),
  valid dimensions by construction; index arrays are no longer
  ENHANCED_FILL-driven (values keep the pattern hook: 2 value sites);
  invalid-input tripwire → BI + skip (never the unguarded oracle, never a
  silent skip, never candidate blame). No rank/nonsingularity requirement
  added. Nonsquare case: §17.
* **47 (SpMV):** unique `(row,column)`; values/x/y keep ENHANCED_FILL
  (3 sites); deterministic candidate-independent generator; same tripwire
  (47's oracle has its own range guard — untouched; the tripwire protects
  the naturally unguarded candidate from invalid harness input). No new
  rank requirement.
* **48 (sparse AXPY):** unique indices per vector, sorted ascending
  (unique ⇒ strictly), values keep ENHANCED_FILL (2 sites); tripwire checks
  index range AND result-buffer length == N before the unguarded oracle
  scatter; result-length grading itself is inherent in the size-checking
  comparator (Wave-1b SIZE_MISMATCH path). No matrix semantics imported.

## 10. reduce26 (A5)

* **Primary input domain:** unchanged `ENHANCED_FILL(x, 1.0, 100.0)` —
  x ∈ [1,100]; no 0/near-zero introduced. Adversarial patterns stay a later
  enhanced-wave decision.
* **Exact comparator branches** (`pareval_harness::compareProductOfInverses`,
  in 26's cpu.cc; r = reference, c = candidate, n = actual input length
  `x.size()`, u = 2^-53 = DBL_EPSILON/2, eps_rel = 8·n·u):
  A) r NaN/Inf → baseline_incompatible (existing BI transport, not a model
  failure); B) r finite ∧ c NaN/Inf → FAIL; C) r == 0.0 exactly → PASS iff
  |c| ≤ DBL_MIN; D) 0 < |r| < DBL_MIN → baseline_incompatible; E) otherwise
  PASS iff |c − r| ≤ eps_rel·|r|. **No absolute floor, no `max(1,|r|)`.**
  Rules A/B and the bounded MISMATCH reporting delegate to the shared
  role-aware `reportAndCompareScalarImpl` (Wave-1 semantics unchanged);
  rule D is decided first (a subnormal is finite) and travels over the
  EXISTING marker line — the frozen transport vocabulary has exactly one
  marker and the Python classification keys on marker+nonce, not the reason
  substring. No new verdict class, no new marker.
* **Operation semantics:** oracle untouched; no multiplication-order
  prescription anywhere.
* **Coverage (A5.4), stated separately:**
  - **in-domain end-to-end:** rules B and E exercised through the real
    driver at the final S/M/L (good/NaN/±4nu/±16nu candidates, §18/§19/§22);
  - **synthetic comparator-branch:** rules A, C, D (and E boundaries incl.
    the exact 8nu edge) covered ONLY by the unit probe against the
    production comparator (16/16 branch checks green, §19). It is
    explicitly NOT claimed that exact-zero or nonzero-subnormal references
    were reached by primary-domain S/M/L end-to-end runs — under x ∈ [1,100]
    and S/M/L = 15/64/256 they are not regularly reachable (window ends
    n≈308).

## 11. search38 (A6.1)

* **OOB fix:** try i==1 now overwrites `min(20, x.size())` elements —
  nothing else changed; mathematical search/sentinel semantics untouched.
* **Small-N evidence:** ASan+UBSan runs at sizes 0, 1, 2, 7, 19, 20, 21 —
  all clean, all `Validation: PASS` (previously: heap-buffer-overflow at
  every size < 20, SEGV at 0).
* **`numTries = 10` unchanged** — benchmark-local exception to the
  validation-attempt contract, deliberately NOT normalized here:
  **`QUEUED FOR WAVE 2B — search38 validation-attempt normalization`**. The
  frozen D2.4 cost model already carries this exception explicitly
  ("MAX_VALIDATION_ATTEMPTS = 2 … exception: 38 hardcodes 10 — documented").

## 12. sort41 (A6.2)

* **k domain / generation:** `k = rand() % x.size() + 1` ∈ [1, n] in BOTH
  draw sites — validate() and the timing-path reset() (the domain table's
  queued fix names the driver draw as such; reset()'s k=0 fed `x_copy[-1]`
  through `best()` as well). k=0 is now unreachable, k=n reachable.
* **n = 0:** explicit harness guard before any draw — no modulo-zero, no
  `x_copy[-1]`, no candidate evaluation; the size-0 instance is announced
  via the existing BI transport (verified end-to-end incl. under
  `-DNDEBUG`: marker + `Validation: PASS` → parser precedence BI).
* **Boundary tests:** oracle probe k=1 (minimum) / k=n (maximum) /
  duplicates counted (multiset: [5,3,3,9] → k=2 gives 3; all-equal arrays;
  prompt example under the committed convention → 2) all green; driver draw
  formula covers [1,n] and never 0; ASan-clean at sizes 1 and 2 (size 1
  previously drew the deterministic invalid k=0).
* **Prompt example untouched.**

## 13. transform59 (A7.1)

* **Candidate independence:** `correctMapPowersOfTwo` now calls
  `pareval_harness::referenceIsPowerOfTwo` (the prompt's total short-circuit
  predicate) — no candidate symbol computes any part of the expected result
  (repo-wide check §25; the only remaining `isPowerOfTwoHOST` use sits in
  the thesis-dead CUDA/HIP branch and is baseline-local).
* **Mandated negative test:** a probe links a candidate whose
  `isPowerOfTwo` is deliberately wrong (`x == 7`); the trusted oracle's
  expected result is UNCHANGED (documented example reproduced exactly:
  [8,0,9,7,15,64,3] → [T,F,F,F,F,T,F]) and totality corners hold (0, −8,
  INT_MIN, INT_MAX → false; 1, 2^30 → true). End-to-end, the same wrong
  candidate is now REJECTED (`Validation: FAIL`) — before this fix it would
  have self-validated. The correct candidate passes.

## 14. graph19 (A7.2)

* **State reset:** validate() zero-fills A before every attempt (the
  generator only adds edges). Family semantics untouched: unit edges,
  unreachable = INT_MAX, self distance = 0, INT_MAX/negative normalization
  unchanged.
* **Attempt-order independence evidence:** probe over 4 attempts —
  with reset: densities 0.5922/0.6041/0.6045/0.6044 (stable ≈ one-shot
  level, spread < 0.013); counterfactual without reset: 0.5876 → 0.8311 →
  0.9280 → 0.9717 (the audited #77 accumulation reproduced). Real 2-attempt
  driver runs PASS on serial/omp/mpi(2 ranks) and under NDEBUG.
  (The TIMING path's reset() keeps the historical accumulation — W2A-I8;
  documented in §26 and queued.)

## 15. dense02 nonsquare (A8.1)

One additional deterministic case per validate(): M = TEST_SIZE,
K = TEST_SIZE/4, N = TEST_SIZE/2 (pairwise distinct for TEST_SIZE ≥ 4;
mirrors the timed geometry), unseeded-rand inputs, full C (M·N) graded with
the existing 1e-4 comparator. Discrimination proven: a candidate correct
only for M==K==N passes every square trial and FAILS the nonsquare case
(§19). Cost: one extra oracle call ≈ T³/8 — measured 0.092 s at L=1536
(≈ 7.7% of the square call); the I3 budget unit (ONE serial oracle call)
is untouched, the per-validate cost note is recorded for the cost model.

## 16. dense04 nonsquare (A8.2)

Deterministic M = TEST_SIZE/2 ≠ N = TEST_SIZE (TEST_SIZE ≥ 2; the timed
geometry's ratio); the ENTIRE expected output shape (all M entries) is
graded via the size-checking comparator. Square-assumption candidate FAILS
the case, correct candidate passes. Extra oracle cost 0.0055 s at L=4095.

## 17. sparse46 nonsquare (A8.3)

Deterministic M = TEST_SIZE, K = TEST_SIZE/4, N = TEST_SIZE/2 (TEST_SIZE ≥
4); sparse coordinates drawn uniquely WITHIN their respective dimensions
(A: M×K, X: K×N — unique-coordinate contract preserved); tripwire guards;
full Y (M·N) graded at 1e-4. Square-assumption candidate FAILS, correct
candidate passes.

**A8.4:** none of this reinterprets S/M/L — the axis stays
`ENHANCED_TEST_SIZE`; the nonsquare cases are additional shape probes inside
validate().

## 18. Baseline-as-candidate results (A9.1)

Canonical correct candidates (forward wrappers onto the real `correct*`
oracles, or an own correct implementation for 59) through the REAL driver
path, authenticated transport (fresh 128-bit token per launch), for ALL 12
benchmarks: 02 04 19 26 38 41 45 46 47 48 49 59 →
**`Validation: PASS nonce=<token>` in 12/12 serial, 12/12 OpenMP, 12/12 MPI
(real `mpirun -n 2`), 12/12 serial `-DNDEBUG`** — 0 BI markers, exactly one
authentic Validation line per launch.

Additional evidence produced by the same runs: sparse45's executable
minimum under D4 is now the mathematical N ≥ 1 (ASan-clean PASS at N = 1,
2, 4 — the random generator was baseline_incompatible at N ∈ 1..3);
sparse49 ASan-clean PASS at N = 1, 2, 4, 16.

## 19. Negative discriminator results (A9.2)

| Case | Expected | Result |
|---|---|---|
| 45 wrong solution (x[0]+1) | FAIL | ✓ |
| 45 transposed/legacy sparse assumption (solves Aᵀx=b) | FAIL | ✓ |
| 45 synthetic boundary +5e-4 (inside 1e-3) | PASS | ✓ |
| 45 synthetic boundary +2e-3 (outside) | FAIL | ✓ |
| 49 wrong L (band entry +1) | FAIL | ✓ |
| 49 shape mistake (column-major factors) | FAIL | ✓ |
| 49 boundary +5e-4 / +2e-3 | PASS / FAIL | ✓ / ✓ |
| 26 candidate NaN | FAIL (rule B) | ✓ |
| 26 relative error 4·n·u (inside 8·n·u) | PASS | ✓ |
| 26 relative error 16·n·u (outside) | FAIL | ✓ |
| 26 exact-zero branch (synthetic, production comparator) | per rule C (5 cases) | ✓ |
| 26 subnormal-reference branch (synthetic) | BI (rule D, 2 cases) | ✓ |
| 26 no-absolute-floor probe (tiny normal r, abs err 1e-9) | FAIL | ✓ |
| 38 small N (0,1,2,7,19,20,21) ASan | clean PASS | ✓ 7/7 |
| 38 wrong index (+1) | FAIL | ✓ |
| 41 k=1 / k=n / duplicates / all-equal (oracle probe) | exact values | ✓ 8/8 |
| 41 wrong value (+1) | FAIL | ✓ |
| 41 size-0 spec | BI, no UB (also NDEBUG) | ✓ |
| 59 deliberately wrong candidate helper | oracle unchanged + FAIL | ✓ |
| 19 attempt-order/state-leak probe (4 attempts) | independent densities | ✓ |
| 02 / 04 / 46 square-assumption candidate | FAIL in the nonsquare case | ✓ / ✓ / ✓ |

**Tolerance-coverage caveat for 45/49:** the negative candidates lie far
outside the current 1e-3 tolerance, so the expected FAIL is unambiguous —
these tests prove basic discrimination, NOT that the existing tolerance is
sharp; sharpness is audited separately in §6a/§8a and queued.

## 20. Serial / OpenMP / MPI results (A9.3)

§18: every changed benchmark built and validated under all three execution
models; MPI with a real `mpirun -n 2` (exactly one authentic Validation
marker per launch). No new MPI semantics; the new constructions run
identically on every rank (deterministic unseeded rand) and keep the BCAST
convention.

## 21. NDEBUG results (A9.4)

12/12 good candidates PASS with `-DNDEBUG`; the 41 n=0 guard fires under
`-DNDEBUG` (BI + no UB). All new bounds/size/invalid-harness guards are
plain `if`s — none exists only as `assert`.

## 22. Direct final S/M/L validation binaries (A9.5)

Productive validation binaries built DIRECTLY with the frozen defines and
executed (no specs generated): 45 @ `-DENHANCED_TEST_SIZE=128/512/1536`,
49 @ 16/128/1024, 26 @ 15/64/256 → **9/9 authenticated PASS**. The
productive code technically carries the final sizes today.

## 23. Existing regression suites (A9.6)

Real Python 3.8.20 (`pareval-py38`, g++ 12.2 + Open MPI): all suites green —
`test_comparator_semantics` (all checks incl. real-driver builds passed),
`test_evaluation` 27, `test_enhanced` 11 groups, `test_feedback` 8,
`test_orchestrator` 12 groups, `test_backfill` 7 groups, `test_overview` 7
groups, `test_generation` 10 groups, `test_cleaning` 13;
`python -m compileall` over the whole pipeline rc=0 (bytecode redirected
outside the repo). No Python production code was changed in this wave and
no 3.8 incompatibility introduced.

## 24. A9.7 productive runtime verification

Setup: pareval-thesis container (g++ 13.3.0, Ubuntu 24.04), pipeline flags
`-std=c++17 -O3 -DUSE_SERIAL "-DDRIVER_PROBLEM_SIZE=(1<<4)"`, no NDEBUG;
host i7-12700H (20 threads), fresh boot (`up 7 min`), load 0.21 (quiet);
3 independent single-call repetitions (59: 5); sub-ms benchmarks measured in
blocks (26: 3×200 000 calls; 47: 3×50; 38: 3×100 000 with per-call input
mutation after the first attempt collapsed to ~1 call via GCC IPA
pure-const hoisting of the NO_INLINE oracle — that first block is invalid
and was discarded). Timed object: ONLY the serial trusted oracle call on
the PRODUCTIVE Wave-2A validation input path (probes include the real
cpu.cc and call the shipped constructors).

| Benchmark | Frozen L | Frozen runtime (median) | New measurements (s) | New median | Ratio frozen/new | Budget (10 s) |
|---|---|---|---|---|---|---|
| sparse45 (D4 path) | 1536 | 1.30 (band 1.15–1.45) | 0.5205 / 0.5152 / 0.5184 | **0.518** | 2.51 → investigated below | ✓ 19× |
| sparse49 (D5 path) | 1024 | 0.73 (band 0.65–0.80) | 0.6673 / 0.6672 / 0.6916 | **0.667** | 1.09 | ✓ 15× |
| reduce26 | 256 | ~1e-5 (table) | 3.667/3.727/3.724e-7 per call | **3.72e-7** | ~27 (see note) | ✓ 2.7e7× |
| sparse46 | 512 | 1.61 | 0.1769 / 0.1810 / 0.1836 | **0.181** | 8.9 | ✓ 55× |
| sparse47 | 4096 | 9.92e-3 | 3.812/3.600/3.786e-3 per call | **3.79e-3** | 2.6 | ✓ 2639× |
| sparse48 | 16777216 | 7.39e-2 | 0.0182 / 0.0183 / 0.0185 | **0.0183** | 4.0 | ✓ 546× |
| search38 (worst case all-odd) | 4096 | 3.40e-6 | 9.864/9.837/9.830e-7 per call | **9.84e-7** | 3.5 | ✓ 1e7× |
| sort41 | 16777216 | 3.43 | 0.7694 / 0.7593 / 0.7356 | **0.759** | 4.5 | ✓ 13× |
| transform59 | 25000000 | 0.136 | 0.0312–0.0327 (5 reps) | **0.0321** | 4.2 | ✓ 311× |
| graph19 | 4096 | 0.352 | 0.0350 / 0.0044 / 0.0400 | **0.0350** | 10.1 (instance-dependent BFS; all ≪ budget) | ✓ 286× |
| dense02 (square, unchanged path) | 1536 | 5.379 | 1.140 / 1.187 / 1.325 | **1.187** | 4.5 (control) | ✓ 8.4× |
| dense02 nonsquare probe (NEW call) | (1536,384,768) | — | 0.092 (1 rep) | 0.092 | new call, 7.7% of square | ✓ |
| dense04 (square, unchanged path) | 4095 | 0.061 (loaded) / 0.019 (quiet) | 0.0110 / 0.0112 / 0.0113 | **0.0112** | 1.7–5.4 (control) | ✓ 893× |
| dense04 nonsquare probe (NEW call) | (2047,4095) | — | 0.0055 (1 rep) | 0.0055 | new call | ✓ |
| **CONTROL: 45 random-COO oracle (code UNCHANGED)** | 1536 | 5.659 (pessimistic; session band 3.195–8.349) | 0.5607 / 0.5520 / 0.5602 | **0.560** | **10.1 (5.7 vs band low end)** | — |

**A9.7.1:** no serial oracle call exceeds 10 s — no budget violation, no
BLOCKED part. The changed benchmarks hold the budget with ≥ 13× margin.

**A9.7.2 — investigation of every reproducible >2× deviation.** Deviations
>2× exist for most rows — uniformly in the FASTER direction — and, decisively,
for the **unchanged-code controls too**: the byte-identical random-COO
oracle path of 45 runs 5.7–10.1× faster than its frozen same-host evidence,
dense02's unchanged square oracle 4.5×, and the unchanged oracles of 41/59/48
4.0–4.5×. The frozen evidence was measured on the same laptop in a
documented thermally degraded state (the approval report records 1.47×
drift on identical work within one session and a 2.6× spread across
medians-of-3 of the same binary); today's measurements come from a fresh
boot at load 0.21. A host-state shift hits changed and unchanged code
alike — and the changed constructions shift LESS than their unchanged
controls (45: 2.5× vs control 5.7–10.1×), i.e. in the conservative
direction. Consistency check with theory: the 45 oracle densifies and its
O(N³) elimination cost is input-independent — measured back-to-back today,
D4 input 0.518 s ≈ random input 0.560 s (ratio 1.08), exactly the
theoretical relationship; the frozen session's apparent 4× gap between the
two inputs was host drift between measurement windows, documented there.
reduce26's larger factor is additionally explained by measurement mode: the
frozen figure was a cold single call dominated by first-touch allocation of
the oracle's push_back copy; a 200 000-call block amortizes the allocator
(plus the host shift). search38's first measurement attempt was discarded
as a compiler artifact (IPA pure-const hoisting), the corrected
input-mutating block is reported. **Conclusion: no deviation is
attributable to the productive implementation; the frozen runtime evidence
and the D2.4 cost model still describe the implementation** (same
asymptotics, same or larger margins; the only new cost terms are the three
declared nonsquare probe calls, each far below its square sibling). The
frozen Domain Table was NOT recalibrated. **A9.7 = PASSED.**

## 25. Scope audit (A10)

* **A10.1 no prompt edits:** `git diff --name-only` = 12 files under
  `drivers/cpp/benchmarks/` + `thesis/enhanced_tests/benchmark_shapes.json`;
  no file under `thesis/prompts/`. ✓
* **A10.2 no results edits:** `git status --porcelain thesis/results` empty. ✓
* **A10.3 no spec regeneration:** no `specs.jsonl`, `spec_gate_report`,
  cache or hash artifact changed; the ONLY regenerated artifact is
  `benchmark_shapes.json` under the explicit W2A-I4 exception (§26b). ✓
* **A10.4 domain contracts unchanged:** `thesis/docs/benchmark-domain-table.json`
  untouched (tracked, clean in git); S/M/L, gamma, lattices, k-policy,
  pivots, eps_rel contract all implemented exactly as frozen — verified by
  the independent probe checkers (D4CHECK/D5CHECK green at all frozen
  sizes) and the 8·n·u branch probe. No domain decision silently rewritten. ✓
* **A10.5 candidate independence:** repo-wide grep over all `baseline.hpp`:
  no trusted path calls any candidate entry point; 59's CPU oracle uses the
  harness predicate (the wrong-helper probe proves behavioral independence). ✓
* **A10.6 helper collisions:** all new namespace-level helpers live in
  `pareval_harness`; the pre-existing global collision names in touched
  files were moved into it; no new global-namespace symbol was introduced
  (only thesis-dead gpu.cu/kokkos.cc still carry the old globals). ✓

**A10 = PASSED.**

## 26. Timed-workload audit (A10.7) — determined, NOT changed

| Benchmark | Validation construction after 2A | Timed construction after 2A | Relation |
|---|---|---|---|
| 45 | D4 dominant integer COO, x_gen, exact b | `createRandomLinearSystem` (random COO, duplicates, singularity-prone) at DRIVER_PROBLEM_SIZE | **intentionally different** (W2A-I8) |
| 49 | D5 band L·U ground truth | random COO (≈100% zero-pivot NaN factorization) | **intentionally different** |
| 46/47/48 | unique coordinates/indices + value fills | random draws WITH duplicates (in-range) | intentionally different |
| 26 | fillRand [1,100] (identical distribution) | fillRand [1,100] | same |
| 38 | ENHANCED_FILL [1,100] + size-safe try-1 overwrite | all-odd + two mid-quadrant evens | intentionally different (unchanged) |
| 41 | fill [0,10000) + k ∈ [1,n] | same fill + k ∈ [1,n] (same UB fix applied to the identical draw formula) | same class |
| 19 | fresh zeroed graph per attempt | reset() still accumulates edges across timing iterations (unchanged) | intentionally different |
| 02/04 | square trials + nonsquare probe | nonsquare timed geometry (unchanged) | intentionally different |
| 59 | trusted predicate oracle | candidate map on [1,1025) fill (unchanged) | unchanged |

* **A10.7.1 sparse45:** YES — the timed input can still produce singular
  matrices (certain at the enhanced-build timing size 16: nnz = 25 < N
  cases measured 200/200 singular in the frozen evidence; 3–6%
  near-singular at 1024), empty COO structure at tiny sizes, and
  non-finite solver states. A candidate that detects a zero pivot /
  singular system and exits early appears faster without implementing the
  intended workload → timing bias possible.
  **`QUEUED DECISION — timed workload construction for sparse45`**
  (→ `QUEUED FOR DEDICATED TIMING WAVE`). Not repaired here.
* **A10.7.2 sparse49:** YES — the timed input makes the unpivoted
  factorization break down essentially always (frozen evidence: 51% of
  output entries non-finite at N=1024); zero pivots, non-finite
  decompositions and early-abort paths are the NORMAL case. Same bias
  mechanism, stronger.
  **`QUEUED DECISION — timed workload construction for sparse49`**
  (→ `QUEUED FOR DEDICATED TIMING WAVE`). Not repaired here.
* **A10.7.3:** validation and performance construction were NOT coupled; no
  timing semantics was frozen or changed in Wave 2A. Additional timing-wave
  notes queued: graph19's reset() accumulation across timing iterations;
  sparse-family timed inputs still violate the duplicate-free contract
  (values not graded during timing, but the workload is out-of-contract
  input). Assigned wave: **DEDICATED TIMING WAVE** (methodically cleaner
  than Wave 2B).

**A10.7 = DOCUMENTED.**

## 26a. Pilot comparability / input-distribution change

sparse45 and sparse49 receive a FUNDAMENTALLY different validation input
construction after Wave 2A than in pilot_001 (random COO → constructive
D4/D5 instances; 49 additionally moves from a ~vacuous NaN-masked
comparison to a real ground-truth comparison; 26 moves from an absolute
1e-4 scalar epsilon to the frozen relative D6 rules). Therefore:

* pilot_001 remains historically unchanged (read-only, not migrated);
* pilot_002 will use the new constructive contracts for these benchmarks;
* verdict/pass-rate differences between pilot_001 and pilot_002 for 45/49
  (and 26) can NOT be interpreted as model or pipeline improvement alone —
  the validation input distribution itself changed;
* pilot_001 and pilot_002 are directly comparable for these benchmarks only
  with this explicit methodological/provenance caveat. The change is
  intentional and methodologically necessary (the historical 45/49
  validation was demonstrably degenerate: BL-16/17/21, F5–F9), and this
  caveat must remain visible in the thesis evaluation.

## 26b. benchmark_shapes consistency after Wave 2A (A10.8)

* **Generator:** `thesis/enhanced_tests/derive_shapes.py` — reads the
  benchmarks' `cpu.cc` validate() bodies, writes ONLY
  `thesis/enhanced_tests/benchmark_shapes.json` (single `write_text` on
  `SHAPES_PATH`; no specs, no hashes, no caches, no results). Isolated
  regeneration is therefore safe under W2A-I4.
* **Pre-regeneration `--check`:** stale rows exactly
  `sparse_la/46, 47, 48, 49` — precisely the four whose fill-site structure
  Wave 2A changed; all 56 other rows unchanged.
* **Regenerated (not hand-edited).** Generator-produced diff:
  46: 6 → 2 fill sites (index sites now constructive; 2 value sites
  remain), 47: 5 → 3 (values, x, y), 48: 4 → 2 (two value sites),
  49: 3 → 0 (fully constructive D5 generation — "no ENHANCED_FILL site").
  `explicit_values_supported` stays `false` for all four (no downstream
  spec-semantics change). 45 unchanged (0 sites before and after).
* **Post-regeneration `--check`:** "stored shapes match the derivation." ✓
* **Verified against current code** for all 12 touched benchmarks (02/04:
  2 sites n2+n2 / n2+n unchanged; 19: 0 unchanged; 26/38/41/59: 1 site "n"
  unchanged).
* **One explained, documented delta vs the READ-ONLY domain table:** the
  frozen table's `fill_effect_status` snapshot for 49
  (`FILL_SITE_PRESENT_EFFECT_NOT_VERIFIED`) describes the PRE-Wave-2A
  structure; after the D5 construction 49 has no fill site. The table is
  frozen read-only this wave (W2A-I2); this report is the provenance source
  for the delta, and the fill_effect refresh belongs to the enhanced
  pattern-policy wave (queued, §29). This is a known, explained
  consequence of a Wave-2A code change — not an unexplained contradiction
  (A10.8.4 does not fire).

**A10.8 = REGENERATED_AND_CONSISTENT.**

## 27. Changed-file list

```
 M drivers/cpp/benchmarks/dense_la/02_dense_la_gemm/cpu.cc            (nonsquare case)
 M drivers/cpp/benchmarks/dense_la/04_dense_la_gemv/cpu.cc            (nonsquare case)
 M drivers/cpp/benchmarks/graph/19_graph_shortest_path/cpu.cc         (per-attempt reset)
 M drivers/cpp/benchmarks/reduce/26_reduce_product_of_inverses/cpu.cc (D6 comparator)
 M drivers/cpp/benchmarks/search/38_search_find_the_first_even_number/cpu.cc (OOB fix)
 M drivers/cpp/benchmarks/sort/41_sort_k-th_smallest_element/cpu.cc   (k in [1,n], n=0 guard)
 M drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc  (D4 construction)
 M drivers/cpp/benchmarks/sparse_la/46_sparse_la_spmm/cpu.cc          (unique coords, tripwire, nonsquare)
 M drivers/cpp/benchmarks/sparse_la/47_sparse_la_spmv/cpu.cc          (unique coords, tripwire)
 M drivers/cpp/benchmarks/sparse_la/48_sparse_la_sparse_axpy/cpu.cc   (unique indices, tripwire)
 M drivers/cpp/benchmarks/sparse_la/49_sparse_la_sparse_lu_decomp/cpu.cc (D5 construction)
 M drivers/cpp/benchmarks/transform/59_transform_map_function/baseline.hpp (independent oracle)
 M thesis/enhanced_tests/benchmark_shapes.json                        (regenerated by its generator)
?? thesis/evaluation/wave2a_domain_critical_implementation_report.md  (this report)
```

All measurement/probe/candidate artifacts live outside the repository
(session scratchpad `w2a/`).

## 28. Per-gate status table

| Gate | Status |
|---|---|
| A1 sparse shared contract | **IMPLEMENTED** |
| A2 sparse45 core | **IMPLEMENTED** |
| A2.4 sparse45 pattern mapping | **QUEUED** (frozen contract detail not found — later enhanced-pattern policy; admissible per A11.2) |
| A3 sparse49 | **IMPLEMENTED** |
| A4 sparse46/47/48 | **IMPLEMENTED** |
| A5 reduce26 | **IMPLEMENTED** |
| A6 search38/sort41 | **IMPLEMENTED** |
| A7 transform59/graph19 | **IMPLEMENTED** |
| A8 nonsquare 02/04/46 | **IMPLEMENTED** |
| A9 correctness regression | **PASSED** (111/111 checks + 9/9 Python-3.8 suites) |
| A9.7 runtime verification | **PASSED** (no budget violation; all >2× deviations attributed to host state via unchanged-code controls) |
| A10 scope audit | **PASSED** |
| A10.7 timed-workload audit | **DOCUMENTED** |
| A10.8 benchmark_shapes consistency | **REGENERATED_AND_CONSISTENT** |

## 29. Follow-up scope

**A) BLOCKED items:** none.

**B) QUEUED decisions:**
1. `QUEUED — FROZEN CONTRACT DETAIL NOT FOUND (sparse45 EnhancedFill
   pattern mapping)` → enhanced pattern-policy wave (A2.4).
2. sparse49 fill-hook pattern mapping → `QUEUED FOR ENHANCED PATTERN-POLICY
   WAVE` (same gap; 49 now has 0 fill sites).
3. `QUEUED DECISION — sparse45 candidate tolerance vs. constructive
   conditioning` (gap ≈ 2.3e10 in the shared max-abs metric).
4. `QUEUED DECISION — sparse49 candidate tolerance vs. constructive
   conditioning` (reference error exactly 0; gap not finitely expressible).
5. `QUEUED FOR WAVE 2B — search38 validation-attempt normalization`
   (`numTries = 10`; cost model already accounts for the exception).
6. `QUEUED DECISION — timed workload construction for sparse45`
   → `QUEUED FOR DEDICATED TIMING WAVE`.
7. `QUEUED DECISION — timed workload construction for sparse49`
   → `QUEUED FOR DEDICATED TIMING WAVE`.
8. graph19 timing-path reset accumulation; sparse-family timed inputs still
   duplicate-laden → DEDICATED TIMING WAVE notes.
9. Domain-table `fill_effect_status` refresh for 49 (and the index-site
   notes of 46/47/48) → enhanced wave (table read-only this wave; §26b is
   the provenance source until then).
10. benchmark_shapes.json regeneration: **not queued — already regenerated
    and consistent** (§26b).

**C) Completed items that MUST NOT be reopened** (unless new code changes
their premises, stored evidence is refuted, or the user reopens them):
the D4 construction and grading of 45; the D5 construction, bit-exact
selftest and grading of 49; the unique-coordinate/index generators and
tripwires of 45–49; the D6 comparator of 26; the 38 OOB fix; the 41
k-domain fix and n=0 guard; the 59 independent oracle; the 19 validation
reset; the 02/04/46 nonsquare cases; the regenerated benchmark_shapes.json.

## 30. Remaining queued work for Wave 2B

* search38 validation-attempt normalization (B.5).
* Further non-domain-critical benchmark/validator fixes from the frozen
  queues: sentinel/UB repairs (19 sentinel collapse, 28, 35, 20, 21, 23,
  24, 33, 51), 07 top-level conjugation (I12), sort40/42/43 invariant
  validators (I10), geometry10/11 family semantics (I11), stencil50
  8-neighbor + 50/52/53/54 full-vector validation (I4/I14).
* Timing decisions are NOT forced into Wave 2B — items B.6–B.8 are
  explicitly `QUEUED FOR DEDICATED TIMING WAVE`.

## 31. Remaining work after Wave 2B (queue only, nothing implemented)

Atomic prompt wave (sole prompt edit point; incl. the 45 duplicate-free
statement, 41 k-semantics, 38 sentinel sentence, power-of-two statements) ·
enhanced pattern-policy/harness wave (pattern mappings, adversarial
value-domain policy, per-benchmark enhanced-size limits for the 22 >4096
rows, input variation for NO_FILL_SITE rows, fill_effect refresh) ·
enhanced spec regeneration against the frozen ladder · static/repair wave ·
assembly wave · reporting/provenance/regression wave · dedicated timing
wave · **pilot_002** (NOT approved).

## 32. `git diff --stat`

```
 .../benchmarks/dense_la/02_dense_la_gemm/cpu.cc    |  34 ++++
 .../benchmarks/dense_la/04_dense_la_gemv/cpu.cc    |  33 ++++
 .../benchmarks/graph/19_graph_shortest_path/cpu.cc |   7 +-
 .../reduce/26_reduce_product_of_inverses/cpu.cc    |  69 ++++++-
 .../38_search_find_the_first_even_number/cpu.cc    |   7 +-
 .../sort/41_sort_k-th_smallest_element/cpu.cc      |  21 ++-
 .../sparse_la/45_sparse_la_sparse_solve/cpu.cc     | 192 ++++++++++++++++++--
 .../benchmarks/sparse_la/46_sparse_la_spmm/cpu.cc  | 168 +++++++++++++++--
 .../benchmarks/sparse_la/47_sparse_la_spmv/cpu.cc  |  79 +++++++-
 .../sparse_la/48_sparse_la_sparse_axpy/cpu.cc      |  79 +++++++-
 .../sparse_la/49_sparse_la_sparse_lu_decomp/cpu.cc | 200 +++++++++++++++++----
 .../59_transform_map_function/baseline.hpp         |  18 +-
 thesis/enhanced_tests/benchmark_shapes.json        |  38 ++--
 13 files changed, 839 insertions(+), 106 deletions(-)
```

## 33. `git status --porcelain`

```
 M drivers/cpp/benchmarks/dense_la/02_dense_la_gemm/cpu.cc
 M drivers/cpp/benchmarks/dense_la/04_dense_la_gemv/cpu.cc
 M drivers/cpp/benchmarks/graph/19_graph_shortest_path/cpu.cc
 M drivers/cpp/benchmarks/reduce/26_reduce_product_of_inverses/cpu.cc
 M drivers/cpp/benchmarks/search/38_search_find_the_first_even_number/cpu.cc
 M drivers/cpp/benchmarks/sort/41_sort_k-th_smallest_element/cpu.cc
 M drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc
 M drivers/cpp/benchmarks/sparse_la/46_sparse_la_spmm/cpu.cc
 M drivers/cpp/benchmarks/sparse_la/47_sparse_la_spmv/cpu.cc
 M drivers/cpp/benchmarks/sparse_la/48_sparse_la_sparse_axpy/cpu.cc
 M drivers/cpp/benchmarks/sparse_la/49_sparse_la_sparse_lu_decomp/cpu.cc
 M drivers/cpp/benchmarks/transform/59_transform_map_function/baseline.hpp
 M thesis/enhanced_tests/benchmark_shapes.json
?? thesis/evaluation/wave2a_domain_critical_implementation_report.md
```

No commit, no `git add`.

## 34. Final classification

All A11.4 conditions hold: A1–A8 IMPLEMENTED (A2.4 admissibly QUEUED per
A11.2 — the source documents queue the pattern mapping to the enhanced
wave, no pattern semantics was invented, nothing is misreported as
FILL_EFFECT_VERIFIED), A9 PASSED, A9.7 PASSED, A10 PASSED, A10.7
DOCUMENTED, A10.8 REGENERATED_AND_CONSISTENT.

**WAVE 2A COMPLETE.**

This does NOT mean: Wave 2B complete, Prompt Wave approved, Enhanced Wave
complete, tool-state work complete, or pilot_002 approved.
