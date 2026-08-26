# Domain Table Approval Report — Domain Approval Wave

Date: 2026-08-25 · Branch: `thesis-static-analysis` · Base commit: `fb40fc893d347feb6df62e05b019a5577067fa79`

This wave freezes the 60-benchmark domain table (S/M/L, numeric gates for
sparse_la/45, sparse_la/49, reduce/26, value-domain concretizations) as the
binding basis for the later benchmark/oracle/generator/prompt/enhanced
implementation waves. **It implements none of those fixes**, and
`DOMAIN TABLE APPROVED` does not mean pilot_002 is approved.

---

## 1. Repository state

```
git branch --show-current   thesis-static-analysis
git rev-parse HEAD          fb40fc893d347feb6df62e05b019a5577067fa79   (= expected)
git status --porcelain (before):
  ?? thesis/evaluation/wave1_final_gate_report.md
  ?? thesis/results/analysis/pilot_001/pilot_readiness_review.md
  ?? thesis/results/analysis/pilot_001/validation-report.md
git diff --stat / --cached --stat (before): empty
```

## 2. Sources read

`thesis/docs/benchmark-domain-table.json` (full, 60 rows),
`fft-family-consistency.md`, `oracle-audit-calibration-45.md`,
`oracle-correctness-audit.md`, `benchmark-example-consistency.md`,
`thesis/evaluation/wave1_final_gate_report.md`,
`thesis/results/analysis/pilot_001/{pilot_readiness_review.md, validation-report.md}` (read-only),
`thesis/enhanced_tests/benchmark_shapes.json` (full), plus current code for
every code-dependent claim (drivers, baselines, config, specs.py, tools.py).

## 3. Frozen invariants acknowledged

I1–I15 were treated as closed inputs: Wave-1 transport semantics untouched;
no global tiny-size rule; the I3 budget unit (ONE serial oracle call ≤ 10 s
median) is now the table's explicit `runtime_budget_note`; stencil50
8-neighbor, sparse duplicate contracts, sparse45/49 construction goals,
reduce26 verdict semantics (incl. no `max(1,…)` floor), dense00 comparison,
sort40/42/43 and geometry10/11 family semantics, FFT conventions,
nonsquare requirements, stencil full-vector plans, and the prompt-wave
exclusivity are all carried into the table as frozen or queued — none
reopened, none contradicted.

## 4. D0 — domain-impact sweep of the known defect list

**34 catalogued defect findings reviewed** (Wave-1b category-C catalogue +
oracle-correctness-audit items + this wave's re-checks against current code):

- **DOMAIN_AFFECTING (18):** 15/16/17/18 (empty input vacuous; 16 additionally
  the recursion/memory ceiling ~12288), 19 (dest-draw loop → executable min 2),
  20 (pixel value domain [0,255]), 21 (value domain [0,100)), 22 (finite
  coordinates), 23 (lowercase a–z strings), 24 (|val| < INT_MAX cast), 25
  (empty input), 33 (|x| ≤ 100 × n ≤ L keeps int sums < 2^31), 34 (operational
  min 1), 36/37/39 (rand()%size → executable min 1), 44 (empty input), 51
  (int-accumulation value bound).
- **BOTH — domain condition AND queued code work (8):** 38 (executable min 20,
  driver OOB-write fix queued, `numTries` hardcoded 10), 41 (k ∈ [1,n] frozen,
  k-generation fix queued), 28 (INT_MAX sentinel collision), 45 (tiny-N empty
  COO; D4 generator queued), 26 (D6 gate), 56 (x > INT_MIN, UB in the oracle
  itself), 58 (|x| ≤ 46340, already frozen), 00 (unpivoted-oracle minor
  condition).
- **CODE_ONLY (8):** 19 sentinel collapse (validator), 35 (sentinel +
  narrowing), 42 (tie ambiguity → I10 validator queued), 59 (candidate-
  dependent oracle, fix REQUIRED), 07 (top-level conjugation, I12), 50+54
  (historical no-length-guard, already fixed in Wave 1b), 02/04/46 (nonsquare
  discriminating case required — documented in the rows per I13), 05/07/08/09
  prompt power-of-two statements (prompt wave).

**SEARCH/38 (explicit check):** cpu.cc `numTries = 10` (not
MAX_VALIDATION_ATTEMPTS); try `i == 1` writes `x[j]` for `j ∈ [0,20)` with no
TEST_SIZE guard → OOB write below 20. Frozen: mathematical minimum 0 (sentinel
semantics), current executable minimum 20, driver fix queued. The bug was NOT
promoted to mathematical semantics.

**SORT/41 (explicit check):** baseline returns `x_copy[k-1]` (1-indexed,
k ∈ [1,n]); driver draws `k = rand() % x.size()` ∈ [0, n-1] → k = 0 reads
`x_copy[-1]` (UB). Frozen: valid domain `1 <= k <= n`; k-generation fix
queued. (Side finding, queued: the prompt's worked example reads as
*distinct-values* k-th smallest — sorted distinct 4th of the example is 6 —
while the oracle implements multiset indexing, which yields 2.)

## 5. S/M/L scope (D1.1) — the size axis

Determined from current code, not from documents:

| Size source | Defined by this table? | Where it actually comes from |
|---|---|---|
| `ENHANCED_TEST_SIZE` | **YES — this is the frozen axis** | per-spec compile define, `run_enhanced_tests.group_defines` → `validate()` via `ENHANCED_TEST_SIZE_DEFAULT` |
| `TEST_SIZE` (correctness stage) | NO | the hardcoded `ENHANCED_TEST_SIZE_DEFAULT(dflt)` argument in each cpu.cc (e.g. 512/1024/128) |
| `DRIVER_PROBLEM_SIZE` | NO | fixed `(1<<8)`, `thesis/evaluation/tools.py:44`; timing loops only |

All 60 `validate()` implementations take their size from
`ENHANCED_TEST_SIZE_DEFAULT` (60/60 verified by grep) — **no benchmark
deviates**. The table's top-level `size_axis` field states this scope and that
reusing these values for another axis is a separate explicit decision. An
unclear axis would have been a hard freeze blocker; it is not.

## 6. D9.15 — evidence sample of the INHERITED table

Deterministic rows (every 6th from 00): 00, 06, 12, 18, 24, 30, 36, 42, 48, 54.
Run **before** D4/D5/D6/D6b/D2/D8, against the inherited artifact.

| Row | Verdict | Claim statuses |
|---|---|---|
| 00 | **CONTRADICTED** | 16 supported, 1 contradicted, 2 stale-line-only |
| 06 | CONFIRMED | 9 supported, 3 stale-line-only |
| 12 | PARTIALLY SUPPORTED | 10 supported, 1 stale-line-only |
| 18 | CONFIRMED | 9 supported, 1 stale-line-only |
| 24 | CONFIRMED | 9 supported, 1 stale-line-only |
| 30 | CONFIRMED | 8 supported, 3 stale-line-only |
| 36 | PARTIALLY SUPPORTED | 7 supported, 1 unsupported, 1 stale-line-only |
| 42 | **CONTRADICTED** | 5 supported, 2 contradicted, 1 unsupported, 2 stale-line-only |
| 48 | PARTIALLY SUPPORTED | 12 supported, 1 stale-line-only |
| 54 | **CONTRADICTED** | 9 supported, 1 contradicted, 1 unsupported, 1 stale-line-only |

**Contradiction classification (D9.15.1):** 4 contradicted claims total.

- **KNOWN STALE (3)** — contradicted by facts D0 established before the
  sample (current harness parameters and the pre-identified 4096
  domain-vs-harness conflict, both named stale classes in this contract):
  1. Row 00: "30 s enhanced run timeout, no config override" — current
     config has `run_timeout_seconds: 60` (raised 2026-08-08). The 2048
     ceiling itself rests on the 10 s oracle measurement and stands.
  2. Row 42: M/L (262144/4194304) presented as enhanced-test scales while
     `max_spec_size = 4096` rejects them — the harness-maximum class D3
     resolves globally.
  3. Row 54: "8192 forced by the harness" — the harness cap is 4096; 8192 is
     host-memory/budget-forced. Same class.
- **NEW CONTRADICTION (1):** Row 42 described the extreme_values fill as
  *float* ±3.4e38; the fill site instantiates with *double*, so pattern 6
  injects ±1.7977e308. The row's domain conclusion (finite, no NaN via the
  fill) is unchanged; the typing/magnitude statement was wrong at birth.

**Threshold:** NEW CONTRADICTIONS = 1 < 2 → **D9.15 = PASSED.** The original
sample result above is frozen; the corrections (D8.1) are recorded in the
table's errata and in `stale_claim_corrected` fields without altering this
sample metric. PARTIALLY SUPPORTED rows carry unverifiable measured figures
(not re-executed in a read-only audit) or minor imprecisions — none is a
substantive domain error.

## 7. D9.18 — reconciliation against `benchmark_shapes.json`

**fill_sites == 0 (10 rows, taken directly from the file):** 01, 15, 16, 17,
18, 19, 23, 25, 44, 45. Every one of these rows now carries
`fill_effect_status = NO_FILL_SITE` plus the required note (no effective
ENHANCED_FILL hook; pattern names can produce input-identical specs; pattern
diversity NOT established; generator/enhanced fix queued where variation is
required). Size variation via `ENHANCED_TEST_SIZE` is a separate, working path
and was checked separately — it works for all 60 (see §5).

**fill_sites >= 1 (50 rows):**
- `FILL_EFFECT_VERIFIED` (3): 00, 05, 30 — pattern-dependent baseline
  *outcomes* measured through the real driver path (F5b census:
  all_zeros/extreme_values/explicit_values non-finite vs random finite at
  identical sizes).
- `FILL_SITE_PRESENT_EFFECT_NOT_VERIFIED` (47): a syntactic site exists; no
  input-level verification evidence exists, and none was fabricated. No new
  full measurement was forced.
- `FILL_INEFFECTIVE` (0): no case with positive evidence of an ineffective
  site.

**Conflicts (D9.18.3):** none active. The nine fill_sites==0 rows that mention
the topic all AGREE with benchmark_shapes.json (several cite it verbatim); row
45 was silent and received the note (its F5b behaviour — identical outcomes
under different pattern names at tiny sizes — is exactly the documented
phenomenon). **D9.18 = PASSED.**

## 8. `.gitignore` / versioning (D8)

`thesis/docs/` (directory ignore, cannot be re-included from below) was
replaced by `thesis/docs/*` plus explicit negations for exactly the five
documents: `benchmark-domain-table.json`, `fft-family-consistency.md`,
`oracle-audit-calibration-45.md`, `oracle-correctness-audit.md`,
`domain-table-approval-report.md`. Verified: all five (and the previously
tracked files) are versionable; an arbitrary new `thesis/docs/` file stays
ignored. **No `git add`, no commit** — the documents appear as `??`.

## 9. Domain-table schema/status changes (D1)

`schema_version` → `benchmark_domain_table.v2`. Top level now carries:
`approval` (version, base commit, date, report), the frozen I3
`runtime_budget_note`, the explicit `size_axis` scope, the global `status`,
and `errata_domain_approval_wave`. Per row: `domain_status` (locally_frozen),
`mathematical_domain` / `current_executable_domain`,
`numeric_gate_status` (+ full `numeric_gate` parameter block for 45/49/26),
`prompt_change_queued` / `generator_change_queued` / `oracle_change_queued`,
`current_enhanced_harness_support`, `fill_effect_status` (+ note),
`value_domain_frozen` where applicable, `smL_change` for changed rows,
`stale_claim_corrected` for corrected rows. Free text was not rewritten;
contradictions are resolved by the structured fields plus errata, so no
double truths: the structured status is authoritative and says so.
transform/59 is no longer pending-free (oracle fix REQUIRED, queued).

## 10. The 4096 domain-vs-harness conflict (D3)

`max_spec_size = 4096` (config.yaml; enforced in specs.py) is a HARNESS cap,
not a domain bound. **22 rows** have at least one frozen size > 4096 (07, 08,
09, 10, 13, 16, 20, 21, 25, 29, 31, 33, 35, 36, 37, 41, 42, 43, 48, 54, 56,
59). For each: mathematical validity holds and the 10 s oracle budget is met
(measured medians in the rows), so the DOMAIN keeps the value and the row is
marked `current_enhanced_harness_support = unsupported_until_harness_wave`.
Rows entirely ≤ 4096 are marked `supported`. `specs.py` was not rebuilt and
no specs were generated; per-benchmark limits are the later enhanced wave's
work.

## 11. sparse_la/45 — D4 numeric gate: **CLOSED**

Frozen construction (validation-only, candidate-independent, deterministic):
square duplicate-free integer COO, diagonal always present; per-row entries
`max(2, round(0.1·N))` incl. diagonal; off-diagonal lattice ±[1..4]
(row-scale regulator M = 4); **gamma definition:**
`|a_ii| = S_i + g_i`, `g_i = ceil(S_i/4)` (floor 1), i.e. multiplicative
`|a_ii| >= 1.25 · Σ_{j≠i}|a_ij|` (**gamma = 1.25**), diagonal sign free;
**x_gen ∈ ℤ ∩ [-8, 8]**; `b = A·x_gen` exact.

Proof-by-execution (3 scales × 5 deterministic fill variants, EVERY partial
row sum instrumented):

| Quantity | Max observed (all 15 runs) | Bound |
|---|---|---|
| max\|A_ij\| | 760 | row scale ≤ 1368 (‖A‖_∞) |
| max\|x_j\| | 8 | lattice |
| max\|A_ij·x_j\| | 6080 | exact (integer < 2^53) |
| max\|partial row sum\| | **10944** | < 2^53 with ≥ 8.23e11× headroom |
| max\|b_i\| | 10944 | exact |
| duplicates / missing diagonals | 0 / 0 | structural |
| min dominance margin g_i | 3 | ≥ 1 strict |
| Varah cond_∞ bound | ≤ 16.80 | N-independent (relative gamma) |

Every operand, every product and every partial sum is an integer < 2^53 →
exactly representable in binary64; `b = A·x_gen` is exact. Real
`correctSolveLinearSystem`: finite in all runs, recovers x_gen to
max|diff| ≤ 2.03e-13 (validation tolerance 1e-3, margin ≈ 5e9×). Runtime at
L=1536: **1.15–1.45 s** median-of-3 (≤ 10 s). S/M/L stay **128/512/1536**.
EnhancedFill invariant: value patterns may vary signs/magnitudes within the
lattice without leaving the proven envelope. No residual-tolerance fallback
was used or needed.

## 12. sparse_la/49 — D5 numeric gate: **CLOSED**

**D5.1 comparison (measured, S/M/L = 16/128/1024, M=4, U-diag = 2^e, e∈[0,5]):**

| | fixed k = 6 | density-preserving k(N) |
|---|---|---|
| S=16 | bw 13, density **0.61–0.65** | k=1, bw 3, density 0.17 |
| M=128 | bw 13, density 0.093–0.099 | k=6 (identical) |
| L=1024 | bw 13, nnz ≈ 12.7–13.3k, density **0.012** | k=51, bw 103, nnz ≈ 101–103k, density 0.097–0.098 |
| bit-exact recovery | YES (all) | YES (all) |
| max real-path intermediate | 208 | 848 |
| oracle runtime at L | 0.67–0.80 s | 0.66–0.67 s |

**Frozen: density-preserving `k(N) = max(1, round((0.1·N − 1)/2))`**
(k = half-bandwidth; k = 1/6/51 at S/M/L). Preserved: the family's ~0.1
relative density at every scale (fixed k would make S effectively dense at
0.61 and L nearly empty at 0.012). Deliberately given up: constant local band
structure across scales. Runtime is k-independent (the oracle densifies to
O(N³) regardless — measured). Lattice: unit-lower L, band-k, off-diagonals
±[1..4]; upper U, band-k, off-diagonals ±[1..4], diagonal 2^e (e ∈ [0,5]) →
all pivots powers of two, every division exact; duplicate-free by
construction (0 observed).

**Real-path evidence (not the abstract form):** the oracle's actual loop
order was mirrored and instrumented — max|intermediate| = 848,
max|division numerator| = 928, min pivot 1, all < 2^53 by ≥ 9.7e12×; the
REAL `correctLuFactorize` returned L and U **bit-exactly in all 9+5
configurations** (3 scales × 3 factor fills for k=6, plus k(N) runs), 0
non-finite. Runtime at L=1024: **0.65–0.80 s** (≤ 10 s). S/M/L stay
**16/128/1024**.

## 13. reduce/26 — D6 numeric gate: **CLOSED**

Operation (current code): `std::reduce` over `data[i] = i%2 ? 1/x[i] : x[i]`,
association unspecified. **Input domain frozen: x_i ∈ [1, 100]** (the
driver's fill range), n ≥ 0 (empty product = 1, degenerate-defined).
Zero/near-zero policy: 0 not in domain; inverses ∈ [0.01, 1] — no
subnormal-producing inverses; a zero or subnormal reference cannot occur
in-domain at n ≤ 256 (worst |ln P| = 128·ln 100 = 589.5 < |ln DBL_MIN| =
707.7). I8's five verdict rules remain in force for out-of-domain probes.

**eps_rel derivation:** u = 2^-53 = 1.110223e-16; oracle ≈ 1.5n roundings
(n/2 divisions + n multiplications), any equivalent ≤ ~2n; all factors
positive → no cancellation; parenthesization differences bounded by the
product rule (~m·u for m factors) → theoretical cross-implementation base
≈ 3.5·n·u; safety factor ≈ 2.3 → **eps_rel(n) = 8·n·u**
(S=15: 1.33e-14, M=64: 5.68e-14, L=256: 2.27e-13).

**Empirical (real oracle vs sequential vs pairwise-tree vs
numerator/denominator, 5 deterministic inputs each):** at 8/64/256 all four
paths finite on every input incl. all-100, all-1, all-50.5, alternating
1/100; max relative disagreement 3.3e-15 → within eps_rel with **≥ 42×
margin**. First in-domain violations measured just above the frozen L:
n=308 → the ORACLE's reference goes subnormal on alternating-1/100 (1e-308 <
DBL_MIN → `baseline_incompatible` under I8 rule 4); n=312 → num/den split
overflows on all-100 (100^156 = 1e312); random-draw num/den overflow from
n ≈ 384–514.

**S/M/L frozen: 15 / 64 / 256** (was 15 / 514 / 16418). The inherited
M=514 already broke the num/den path on RANDOM draws (measured non-finite);
L=16418 was oracle-safe only. L=256 keeps ≥ 52 orders of magnitude margin
against both overflow (worst 1e128 vs 1.8e308) and underflow (worst 1e-128
vs 2.2e-308) for every plausible correct path. Runtime O(n), trivial
(5.7e-4 s measured at 16418; monotone). Meaningful workload is carried by
the timing axis (DRIVER_PROBLEM_SIZE), not by L — numerical neutrality
dominates, as the gate ordering requires.

## 14. D6b — all-60 representability sweep: **CLOSED**

**Stage 1 (all 60, static/mathematical):** 60 classified — **52
NO_REPRESENTABILITY_RISK_FOUND, 8 FLAGGED_FOR_STAGE_2**: 07 (INT), 12 (INT),
26 (OVF/UDF), 40 (OVF), 52 (OVF), 55 (OVF), 56 (INT), 59 (INT). The
explicitly required checks 29/30/32/58 all came back clean (29: double sums
≤ 2e8; 30: prefix sums ≤ 4e5; 32: ≤ 1.7e9 in double; 58 mitigated by the
frozen |x| ≤ 46340) — 33's int-scan risk is bounded in-domain
(|x| ≤ 100 × n = 1e7 → ≤ 1e9 < 2^31, margin 2.1×, identical on every
correct path since prefix values are the *output*).

**Stage 2 (the 8 flagged, instrumented in scratch with concrete numbers):**

| Benchmark | Finding | (i) cap size | (ii) value domain | (iii) impl./prompt contract | Resolution |
|---|---|---|---|---|---|
| 07 | int `n*k` UB > N=46341; at M=65536 the O(N²) path can complete (~4.3e9 iter) with a negative `(n*k)%N` from n=k=32769 | **M 65536→32768** (32767² = 1.07e9 < 2^31); L=2^22 runtime-dead for the naive path (1.76e13 iter vs 60 s) | n/a (index-driven) | "use 64-bit index products" — would be a new prescription | **(i) adopted** (plain size choice) |
| 12 | int combination-count `n(n-1)(n-2)` crosses 2^31 at n=1292; at 2048 every int order overflows (8.58e9; even n(n-1)/2·(n-2)=4.29e9) | **L 2048→1024** (max 1.07e9 < 2^31; runtime ≤ 2.62 s·⅛ ≈ 0.33 s) | n/a | 64-bit prescription — new | **(i) adopted** |
| 26 | num/den split overflow + subnormal reference (see §13) | **M→64, L→256** | keep [1,100] | interleaving prescription — new | **(i) adopted (D6)** |
| 40 | `std::norm` = inf at spike (DBL_MAX/2, DBL_MAX/2) while `std::abs` = 1.27e308 finite (measured) | n/a (size-free) | **[-100,100] frozen** (in-domain max norm 2e4; threshold 1.34e154) | — | **(ii) adopted** — concretizes the driver's existing fill range |
| 52 | 3-term association: oracle's neighbour-first order → inf at ±DBL_MAX while prompt order stays finite (measured) | n/a | **[-100,100] frozen** (max sum 300; threshold DBL_MAX/2) | — | **(ii) adopted** |
| 55 | branchless `(v+\|v\|)/2` → inf at DBL_MAX; `sqrt(v·v)` → inf above 1.34e154 (measured) | n/a | **[-50,50] frozen** | — | **(ii) adopted** |
| 56 | `-INT_MIN` UB — in the ORACLE itself (baseline.hpp:14) | n/a | **x > INT_MIN frozen** (fill [1,100) untouched; same class as 58's frozen bound) | — | **(ii) adopted** |
| 59 | reversed-conjunction/`x & -x`/float-log spellings UB at INT_MIN/INT_MAX; the provided short-circuit predicate is total | n/a | domain stays "any int"; in the fill range [1,1025) every spelling is total and identical | — | **no in-domain divergence**; adversarial-pattern policy queued; the dominant defect is the candidate-dependent oracle (queued, REQUIRED) |

Pattern-injected out-of-range values (extreme_values → ±DBL_MAX/INT_MIN/
INT_MAX regardless of the call-site range; spike_at → DBL_MAX/2) are
**adversarial enhanced-gate coverage, not primary domain** — the same
separation D6.3 makes for reduce/26; the pattern policy is queued to the
enhanced wave and marked per row. Every adopted option is either a plain
size choice or a concretization of an already-documented driver condition —
**no new benchmark semantics, no implementation prescription, no prompt
requirement was chosen unilaterally → 0 `REPRESENTABILITY_DECISION_REQUIRED`,
D6b = CLOSED.**

## 15. All-60 final S/M/L (frozen)

Unchanged from the inherited proposal except rows marked ◄. Axis: benchmark-
local `ENHANCED_TEST_SIZE` domain (§5). E = current enhanced harness support
(`s` ≤ 4096 / `u` = unsupported_until_harness_wave).

| # | S | M | L | E | | # | S | M | L | E |
|---|---|---|---|---|---|---|---|---|---|---|
| 00 | 64 | 512 | 2048 | s | | 30 | 17 | 1021 | 4093 | s |
| 01 | 64 | 512 | 2048 | s | | 31 | 127 | 262144 | 16777216 | u |
| 02 | 64 | 500 | 1536 | s | | 32 | 16 | 257 | 4096 | s |
| 03 | 37 | 1023 | 4093 | s | | 33 | 1001 | 500000 | 10000001 | u |
| 04 | 3 | 513 | 4095 | s | | 34 | 64 | 511 | 4096 | s |
| 05 | 16 | 256 | 4096 | s | | 35 | 512 | 65536 | 4194304 | u |
| 06 | 17 | 255 | 4093 | s | | 36 | 1021 | 1048575 | 16777215 | u |
| 07 | 1024 | **32768 ◄** | 4194304 | u | | 37 | 1024 | 131072 | 16777216 | u |
| 08 | 64 | 8192 | 1048576 | u | | 38 | 21 | 1024 | 4096 | s |
| 09 | 8 | 1024 | 4194304 | u | | 39 | 16 | 128 | 4096 | s |
| 10 | 3001 | 120001 | 4800001 | u | | 40 | 64 | 1024 | 4093 | s |
| 11 | 16 | 256 | 4096 | s | | 41 | 4096 | 262144 | 16777216 | u |
| 12 | 8 | 256 | **1024 ◄** | s | | 42 | 1024 | 262144 | 4194304 | u |
| 13 | 101 | 2003 | 30011 | u | | 43 | 16 | 262144 | 33554432 | u |
| 14 | 4 | 1024 | 4096 | s | | 44 | 33 | 511 | 4095 | s |
| 15 | 64 | 513 | 4096 | s | | 45 | 128 | 512 | 1536 | s |
| 16 | 16 | 1000 | 8192 | u | | 46 | 16 | 128 | 512 | s |
| 17 | 64 | 1024 | 4096 | s | | 47 | 64 | 1500 | 4096 | s |
| 18 | 4 | 1024 | 4096 | s | | 48 | 2048 | 1048576 | 16777216 | u |
| 19 | 16 | 512 | 4096 | s | | 49 | 16 | 128 | 1024 | s |
| 20 | 256 | 1048576 | 67108864 | u | | 50 | 64 | 512 | 4096 | s |
| 21 | 101 | 1000003 | 16777216 | u | | 51 | 15 | 511 | 4095 | s |
| 22 | 4 | 1023 | 4096 | s | | 52 | 17 | 1024 | 4096 | s |
| 23 | 26 | 104 | 4096 | s | | 53 | 127 | 727 | 4093 | s |
| 24 | 16 | 1024 | 4095 | s | | 54 | 7 | 1024 | 8192 | u |
| 25 | 1021 | 1048549 | 268435449 | u | | 55 | 7 | 1024 | 4093 | s |
| 26 | 15 | **64 ◄** | **256 ◄** | s | | 56 | 31 | 100003 | 4194301 | u |
| 27 | 33 | 1024 | 4096 | s | | 57 | 18 | 1024 | 4090 | s |
| 28 | 17 | 1024 | 4093 | s | | 58 | 5 | 257 | 4096 | s |
| 29 | 1023 | 65536 | 2097151 | u | | 59 | 1000 | 1000000 | 25000000 | u |

Decision per row: 55 × APPROVE AS-IS, 3 × CHANGE (07, 12, 26), 0 × BLOCKED.
45 and 49 additionally receive the frozen D4/D5 constructions (values
unchanged).

## 16. Changed S/M/L values with evidence

1. **07 M: 65536 → 32768** — D6b: int `n*k` UB window (threshold 46341;
   measured wrap demo; the O(N²) path can complete at 65536 within the 60 s
   timeout). Power-of-two preserved (2^15, I12).
2. **12 L: 2048 → 1024** — D6b: int combination-index overflow (threshold
   1292, all int evaluation orders overflow at 2048; safe at 1024); runtime
   monotone below the measured 2.62 s.
3. **26 M: 514 → 64, L: 16418 → 256** — D6: measured neutrality window
   (§13); the inherited M already broke a mathematically equivalent path on
   random draws.

## 17. Mathematical vs current executable domain

Split explicitly per row (field pair); divergent rows: 38 (0 vs ≥ 20, driver
fix queued), 41 (k ∈ [1,n] vs driver drawing 0), 36/37/39 (0 vs ≥ 1,
`rand()%size`), 19 (≥ 2, dest loop), 16 (recursion/memory ceiling
~12288), 45 (≥ 1 with D4 construction vs ≥ 4 with the current random
generator — measured), 59 (total predicate vs candidate-dependent oracle),
26 (identical, D6 closed). All others: identical, stated as such. No current
bug was promoted to mathematical semantics (I2).

## 18. Benchmark-local tiny/minimum policy

No global tiny list (I2). `static_base_sizes [0,1,2,7]` remain probing sizes;
per-row `min_size`/`degenerate_cases` say which are defined, which are
degenerate-defined (e.g. empty product = 1 for 26; N ≤ 1 LU trivially
defined), and which are currently non-executable for code reasons only
(§17). Sizes 0/1 stay allowed where mathematically defined.

## 19. D9.16 — final S/M/L vs own row constraints

Checker: benchmark-specific (power-of-two for 05/07/08/09; ≥ 3 points for 12;
≥ 2 for 13/14/19; executable minima for 36/37/38/39/45; k ∈ [1,n] premise for
41; k(N) < N for 49; N ≥ 3 for 50; n ≥ 1 for 27/34/35; numeric row-min vs S;
S<M<L; >4096 marking; gate closure; 59 queue) over the FINAL table.

- **Raw checker findings: 0. Confirmed violations: 0. Checker false
  positives: 0.**
- Negative control executed: three injected violations (07 M=65537 non-power,
  12 S=2, 30 L=10) were all caught → the zero is meaningful, not a silent
  checker.

**D9.16 = PASSED.**

## 20. Domain-induced runtime/workload (D2.4-A)

Size source per stage first (per D1.1): generation — none; compile/static —
`DRIVER_PROBLEM_SIZE=(1<<8)` (tools.py:44), **not this table**; correctness —
hardcoded `TEST_SIZE` defaults + launch grid, **not this table**; dynamic —
same as correctness, **not this table**; **enhanced — `ENHANCED_TEST_SIZE`
per spec: THIS table's axis**; repair — inherits the stages above.

Factors (every value with its source):

| Factor | Value | Source | Stage |
|---|---|---|---|
| benchmarks | 60 | `thesis/prompts/generation-prompts-thesis.json` (60 distinct names, 180 entries) | all |
| enabled models | 11 | `config.yaml models[].enabled` (listed in run manifest) | all |
| execution models | 3 | `config.yaml stages.enhanced_tests.execution_models` | enhanced |
| samples per prompt | 1 | `config.yaml profiles.*.num_samples_per_prompt: 1` | all |
| specs per benchmark | 20 | `config.yaml stages.enhanced_tests.target_cases_per_benchmark` — spec sizes are INSIDE the specs; **no extra S/M/L multiplication** | enhanced |
| oracle calls per spec run | ≤ 2 | `MAX_VALIDATION_ATTEMPTS = 2`, utilities.hpp:35 (exception: 38 hardcodes 10 — documented) | enhanced |
| launch points | 1 per exec model | `enhanced_launch {omp_threads: 4, mpi_ranks: 4}`; `run_enhanced_tests.launch_command` — "deliberately no grid" | enhanced |
| repair rerun factor | 2.805 | frozen pilot_001 record counts: 1111 correctness / 396 baseline = 22220 enhanced / 7920 baseline | all reruns |
| Σ oracle runtime at frozen L | **47.42 s** | sum of the 60 rows' measured L medians (45→1.30 s, 49→0.73 s, 26→1e-5 s, 12→0.33 s from this wave's runs) | enhanced |

Baseline enhanced spec runs: 60 × 33 × 20 = **39,600**; with the pilot-derived
repair factor ≈ **111,100**. Domain-induced serial ORACLE cost:

- **Ladder floor** (exactly one L-sized spec per sample, tiny sizes ≈ 0):
  2 × 33 × ΣL = **0.87 core-h** baseline, **2.4 core-h** with reruns.
- **Worst-case bound** (all 20 specs at L): 2 × 33 × 20 × ΣL =
  **17.4 core-h** baseline, **48.8 core-h** with reruns.

Candidate calls are of the same order (one candidate call per oracle call;
constant unknown — candidates vary). Gate calls (serial baseline selftest,
one per (benchmark, size) spec_key, cached across models) are sub-dominant:
≈ 60 × ~10 sizes × 2 probes × 2 attempts ≪ the above. Reproducible from the
table's own runtime column; no factor was taken from this contract's
examples. **Nothing here is practically untenable.**

## 21. End-to-end full-run range (D2.4-B, existing measurements only)

Sample-iterations (full run): 1980 baseline × 2.805 ≈ 5,554.

| Component | Basis (pilot_001 medians / sums) | Full-run estimate |
|---|---|---|
| static tools | per-sample-iter ≈ 28.2 s (compiler 2.0–3.0, gcc_analyzer 1.2–2.1, clang_tidy 3.9–4.6, cppcheck 0.2–0.6, infer 17–24.6, parcoach 0.03 (mpi), llov 0.5 (omp)) | ≈ **43.5 core-h** |
| dynamic tools | ≈ 32.4 s (asan 2.7/2.9/20.3, tsan 1.9 (omp), memcheck 2.4/2.8, must 64.3 (mpi)) | ≈ **50 core-h** |
| correctness | pilot 1.25 h per 1,111 sample-iters (builds 2.55 s median + grid runs 0.283 s median) | ≈ **6.3 core-h** |
| enhanced (OLD spec sizes) | pilot 3.7 h per 22,220 runs | ≈ 18.5 core-h; superseded post-regeneration by §20's 2.4–48.8 core-h oracle range + candidate calls; build groups **not established** |
| generation | batch mode, queue-dominated wall time | walltime **not established** (token totals exist per model) |
| timed execution | — | **not established** |

CPU/core-hours: known components sum to roughly **100–150 core-h**;
idealized walltime under the configured worker parallelism: **not
established** (no measured effective-parallelism figure exists; none was
invented). No component with existing evidence indicates practical
untenability.

## 22. D9.17 — workload status

Domain-induced workload of the table-governed axis: **QUANTIFIED** (§20),
every factor sourced, size source named per stage, no double multiplication
(spec sizes inside the 20; variants enter only through the measured pilot
rerun ratio; validation attempts applied only to validate(); no grid applied
to the grid-free enhanced launch). **D9.17 = QUANTIFIED.**

## 23–26. Queued downstream changes (D7 — nothing implemented)

- **Prompt (queued to the atomic prompt wave, sole edit point):** the 32
  inherited restriction sentences (rows retain them under
  `prompt_change_queued`), plus: 50 8-neighbor statement (I4), 45
  duplicate-free/square statement, FFT power-of-two statements (I12), 41
  k-semantics clarification.
- **Generator:** D4 construction for 45; D5 construction for 49; unique-
  coordinate contracts 45/46/47/48/49 (I5); nonsquare cases for 02/04/46
  (I13); 38 driver OOB fix + numTries; 41 k-generation fix; input-variation
  hooks for the 10 `NO_FILL_SITE` rows.
- **Oracle/validator:** 59 candidate-dependent oracle (REQUIRED); 07
  conjugation (I12); sort40/42/43 invariant validators (I10); geometry10/11
  family semantics (I11); stencil 50 8-neighbor + 50/52/53/54 full-vector
  validation (I4/I14, 54: out-of-grid = dead); sentinel/UB repairs (19, 28,
  35, 20, 21, 23, 24, 33, 51).
- **Enhanced:** per-benchmark size limits (>4096 rows, §10); adversarial
  fill-pattern policy vs frozen value domains (§14); input-variation for
  `NO_FILL_SITE` benchmarks; spec regeneration against the frozen ladder.

## 27. Append-only audit updates (D8.2)

Each of `fft-family-consistency.md`, `oracle-audit-calibration-45.md`,
`oracle-correctness-audit.md` received exactly one new section at the END —
`Status as of Domain Approval Wave — 2026-08-25 — based on fb40fc8…` —
classifying earlier diagnoses as confirmed / superseded / still open and
adding the D4/D5/D6/D6b evidence. No existing text was reworded, deleted or
silently corrected (verified: appends only).

## 28. Final consistency checks (D9)

1 JSON parses ✓ · 2 exactly 60 IDs ✓ · 3 no duplicates ✓ · 4 S<M<L ✓ ·
5 `domain_status` on every row ✓ · 6 size axis explicit ✓ · 7 no false-ready
(status text scopes the approval; pending/queued fields retained) ✓ ·
8 no frozen decision contradicted ✓ · 9 all >4096 rows marked
enhanced-unsupported (22/22, checker-verified both directions) ✓ ·
10 transform59 queued (REQUIRED) ✓ · 11 search38 executable-domain claim
correct ✓ · 12 sort41 k-domain correct ✓ · 13/14/15 numeric gates complete
(§11–13) ✓ · 16 representability sweep complete (§14) ✓ · 17 budget status
documented per row + top level ✓ · 18 D9.15 original sample preserved (§6) ✓ ·
19 D9.18 reflected in the final rows (fill_effect_status on 60/60) ✓

## 29. Per-gate closure table

| Gate | Status |
|---|---|
| D4 sparse45 | **CLOSED** |
| D5 sparse49 | **CLOSED** |
| D6 reduce26 | **CLOSED** |
| D6b representability | **CLOSED** |
| D9.15 evidence sample | **PASSED** |
| D9.16 size constraints | **PASSED** |
| D9.17 workload | **QUANTIFIED** |
| D9.18 benchmark shapes | **PASSED** |

## 30. Follow-up scope if blocked

Not applicable — no gate is BLOCKED/FAILED/OPEN/NOT QUANTIFIED. For any
future follow-up: the eight gates above are closed with stored evidence and
frozen parameters; they may not be reopened unless new code changes their
premises, stored evidence is demonstrably refuted, or the user explicitly
reopens them (D10.1). All 60 rows are `locally_frozen`; the decisions still
needing HUMAN action are the queued implementation waves (§23–26), not
domain decisions.

## 31. Remaining non-domain open gates (unchanged by this wave)

Benchmark/oracle fixes (§23–26 queues incl. 59 REQUIRED and 07), generator
wave, atomic prompt wave, enhanced-harness wave (per-benchmark limits,
pattern policy, spec regeneration), assembly wave (leaked chain-of-thought),
static/dynamic tool-state gates (LLOV hard blocker, PARCOACH 60 s,
gcc-analyzer FP class), reporting/provenance of the retrospective vacuous-
pass correction, LLOV re-pilot decision, all-60 prompt-consistency gate
(6 INCONSISTENT), pilot_001's NaN-reference blind spot, **pilot_002
approval**.

## 32. Final classification

**DOMAIN TABLE APPROVED** — all D10.3 conditions hold (60/60 rows final,
axis unambiguous, S/M/L frozen and constraint-clean, domains separated,
budget semantics fixed, workload quantified, 4096 conflict methodically
resolved, D4/D5/D6/D6b closed, D9.15/16/18 passed, D9.17 quantified, queued
changes explicit, documents versionable, no frozen decision contradicted).
This does NOT mean: benchmark code repaired, prompts changed, generators
repaired, specs regenerated, or pilot_002 approved.

## 33. `git diff --stat` (tracked files)

```
 .gitignore | 12 +++++++++++-
 1 file changed, 11 insertions(+), 1 deletion(-)
```

(The domain table and the three audit documents were previously IGNORED and
are still untracked — their changes appear as `??` below, not as diffs;
that is exactly the versioning state this wave establishes without
committing.)

## 34. `git status --porcelain` (after)

```
 M .gitignore
?? thesis/docs/benchmark-domain-table.json
?? thesis/docs/domain-table-approval-report.md
?? thesis/docs/fft-family-consistency.md
?? thesis/docs/oracle-audit-calibration-45.md
?? thesis/docs/oracle-correctness-audit.md
?? thesis/evaluation/wave1_final_gate_report.md
?? thesis/results/analysis/pilot_001/pilot_readiness_review.md
?? thesis/results/analysis/pilot_001/validation-report.md
```
