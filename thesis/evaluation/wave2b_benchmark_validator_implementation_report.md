# Wave 2B — Remaining Benchmark / Oracle / Validator Fixes Report

Date: 2026-08-26 · Branch: `thesis-static-analysis` · Base commit: `17404d6d213c56ab05d29823e384c8865acc819f`

This wave implements the remaining ALREADY FROZEN benchmark/oracle/validator
decisions. It takes NO new benchmark semantics; every open finding without a
frozen implementation target is classified and queued, not guessed. No
prompt file edited, no enhanced policy decided, no timing-wave item pulled
forward, no verdict-transport change, no commit, no `git add`.

---

## 1. Repository state

```
git branch --show-current   thesis-static-analysis
git rev-parse HEAD          17404d6d213c56ab05d29823e384c8865acc819f   (= expected; parent d968771…)
git status --porcelain (before): empty (clean)
git diff --stat / --cached --stat (before): empty
```

HEAD "fixes 4" contains exactly the Wave-2A changes plus the Wave-2A report
— no other productive change since Wave 2A, no unclear premise.

## 2. Source-of-truth documents read

Wave-2A report (§29–31 queues in particular), the full domain table (all 60
rows swept for `oracle_change_queued`/`generator_change_queued`; the ~30
candidate rows read in full), domain approval report (queues §23–26, D0
sweep), oracle-correctness audit (BL-01…BL-21, ambiguities, follow-ups,
consolidated change list #64–#77, appended status), FFT family audit
(benchmark sections 05–09, family recommendation, appended status),
benchmark-example-consistency (6 inconsistencies, consequences), Wave-1
final gate report (transport inventory), `benchmark_shapes.json`, plus the
CURRENT code of every touched benchmark (cpu.cc + baseline.hpp), the model
drivers, `utilities.hpp`/`harness-markers.hpp`/`enhanced-fill.hpp`,
`derive_shapes.py`.

## 3. Wave-2A closed gates acknowledged

A1–A10.8 not reopened. Untouched here: sparse45 D4 / sparse49 D5
constructions and tolerances and pattern mappings, reduce26 comparator,
02/04/46 nonsquare cases, S/M/L, numeric gates, the 2A queues (tolerances,
pattern mappings, timing constructions, graph19 timing accumulation,
sparse timed duplicates).

## 4. B0 — complete remaining-queue table

Reconstructed from the artifacts (NOT from this order's example list). The
structured frozen queue is: `oracle_change_queued` on rows 07 (I12), 10/11
(I11), 40/42/43 (I10), 50/52/53/54 (I4/I14); the approval report's
sentinel/UB repair queue "(19, 28, 35, 20, 21, 23, 24, 33, 51)"; the
Wave-2A queue "search38 validation-attempt normalization"; the FFT-family
N=1/shift-UB finding (audit, UBSan-verified in 05/07/08/09).

| Benchmark | Finding | Source | Classification | Frozen target | Implementation status |
|---|---|---|---|---|---|
| search/38 | `numTries = 10` local hardcode | 2A report §29 B.5; table row 38 | A) FROZEN_TARGET | suite-wide `MAX_VALIDATION_ATTEMPTS` | IMPLEMENTED (B1) |
| graph/19 | sentinel collapse: INT_MAX/negatives normalized to −1 | audit #77-adjacent list; D0 CODE_ONLY; table family semantics (self=0, unreachable=INT_MAX) | A | exact scalar comparison, no alias set | IMPLEMENTED (B2) |
| histogram/20 | out-of-domain pixels → OOB write in oracle | sentinel/UB queue; frozen domain [0,255] (prompt) | A | domain tripwire → existing BI transport | IMPLEMENTED (B2) |
| histogram/21 | cast UB outside [0,100] | sentinel/UB queue; frozen domain [0,100] (prompt) | A | tripwire → BI | IMPLEMENTED (B2) |
| histogram/23 | empty-string OOB (unreachable) | sentinel/UB queue | F) effectively closed | none reachable: fillRandString minLen 2 + validate overwrites `s[j][0]` with `'a'+rand()%26`; no ENHANCED hook | NO CODE CHANGE (verified unreachable); prompt sentence queued |
| histogram/24 | `(int)` cast UB ≥ 2^31; negatives swept to bins[0] | sentinel/UB queue + BL-08 | A (domain tripwire) + E (negative-fraction semantics) | frozen domain 0 ≤ v < 2^31 (table); BL-08 "decision deliberately left open" | tripwire IMPLEMENTED (B2); floor-semantics QUEUED_NO_FROZEN_TARGET (B6) |
| reduce/28 | INT_MAX sentinel collision; negative-parity convention; UB-constructed pattern values | sentinel/UB queue; D0 BOTH; table special_conditions + queued prompt contract | A (domain tripwire) + E (parity/sentinel semantics) | frozen domain v ≥ 0 ∧ v ≠ INT_MAX | tripwire IMPLEMENTED (B2); conventions PROMPT_ONLY/queued |
| scan/33 | int-accumulation UB outside \|x\| ≤ 100 | sentinel/UB queue; D0 frozen value bound | A | tripwire → BI | IMPLEMENTED (B2) |
| search/35 | size-0 modulo-zero SIGFPE; not-found sentinel (unreachable) | sentinel/UB queue; frozen min_size 1 | A (guard); sentinel part inert | n==0 → BI, never a candidate verdict | IMPLEMENTED (B2); NEW FINDING: undocumented `numTries = 5` → E (not frozen; queued, cost-model note §28) |
| stencil/51 | int-sum overflow UB outside [0,255] | sentinel/UB queue; D0 value bound; queued prompt contract | A | tripwire → BI | IMPLEMENTED (B2) |
| fft/07 | grading oracle not a DFT (nested conjugation); N=1 conjugation dropped | `oracle_change_queued` "top-level conjugation fix, exactly once (frozen I12)" | A | conj exactly once at top level; oracle NOT replaced | IMPLEMENTED (B3.1) + independent DFT verification PASSED (B3.1b) |
| fft/05/07/08/09 | N=1 shift-by-32 UB in the Rosetta bit-reversal | FFT audit (UBSan receipts per benchmark) | A | guard exactly where the defect exists | IMPLEMENTED (B3.2) |
| sort/40 | validator demands unspecified tie order (BL-12, class E) | `oracle_change_queued` frozen I10 | A | invariant validator: multiset + magnitudes non-decreasing | IMPLEMENTED (B4.1) |
| sort/42 | exact equality vs unstable-sort tie permutation | frozen I10 | A | ranks = permutation, application non-decreasing | IMPLEMENTED (B4.2) |
| sort/43 | field-wise equality vs unstable tie permutation | frozen I10 | A | record permutation + key non-decreasing | IMPLEMENTED (B4.3) |
| geometry/10 | multiplicity/degenerate defects; output form | frozen I11 "hull of the distinct point set" | A | SET semantics (determination §13) | IMPLEMENTED (B5.1) |
| geometry/11 | BL-02/03/04 (not set-invariant; conventions unpinned) | frozen I11 "collinear ≥2 distinct → 2·extent, one point → 0" | A | K1 set-invariant oracle | IMPLEMENTED (B5.2) |
| stencil/50 | 4-neighbor oracle contradicts prompt example; interior-only window | frozen I4 + I14 | A | Moore 8-neighbor + full-vector validation | IMPLEMENTED (B8.1) |
| stencil/52 | interior-only window; boundary rule ungraded | frozen I14 | A | full-vector incl. boundaries | IMPLEMENTED (B8.2) |
| stencil/53 | interior-only window | frozen I14 | A | full-vector incl. boundaries | IMPLEMENTED (B8.3) |
| stencil/54 | interior-only window; boundary semantics ungraded | frozen I14 "out-of-grid = dead, no wrap" | A | full-grid validation; oracle already dead-outside (verified) | IMPLEMENTED (B8.4) |
| scan/34 | empty-subarray / size-0 convention (BL-10/BL-11) | audit: "decision deliberately left open", both | E | none | QUEUED_NO_FROZEN_TARGET (B7) |
| dense_la/00 | absolute 1e-3 tolerance unattainable (BL-01/#71) | audit: decision open | E | none | QUEUED — FROZEN IMPLEMENTATION TARGET NOT SPECIFIED |
| geometry/12/13/14 | n<2/n<3 returns, DBL_MAX sentinel (BL-05/06/07), degenerate-triple counting | audit: decisions open; `oracle_change_queued: none` | B/C/E | none | queued (prompt/enhanced/decision waves) |
| histogram/22 | axis/origin convention | table: "no decision has been recorded yet" | B/E | none | PROMPT_ONLY queue |
| search/36/37/39 | size-0 modulo-zero; tie-break (37) | table: executable min documented, NO repair queued (unlike 35) | E | none | DECISION_NOT_FROZEN (asymmetry to 35 documented) |
| sort/44, graph/15–18, reduce/25/29, transform/57, fill-site/variation items on ~20 rows | generator/input-variation capability gaps | `generator_change_queued: yes — …` prose entries | C) ENHANCED_ONLY | — | queued (enhanced wave) |
| 40/52/55/56/58/59 value-domain adversarial patterns | D6b frozen value domains; pattern policy | approval §14: "policy queued to the enhanced wave" | C | — | queued (enhanced wave; deliberately NOT tripwired here — the frozen line assigns D6b rows' pattern handling to the enhanced wave, the sentinel/UB queue rows to this wave) |
| all Phase-0 example fixes (06/07/09/41/42/50) + restriction sentences | benchmark-example-consistency + rows | B) PROMPT_ONLY | — | §29 prompt queue |
| sparse45/49 tolerances, pattern mappings, timing constructions, graph19 timing accumulation, sparse timed duplicates | Wave-2A queues | D/TIMING/ENHANCED | — | untouched (frozen queues) |

Every `FROZEN_TARGET — IN WAVE 2B` row above is implemented; the B9 sweep
found no further one (the all-60 structured-queue sweep is in §21).

## 5. search38 attempt normalization (B1)

* **Attempts before:** 10 (benchmark-local hardcode). **After:**
  `MAX_VALIDATION_ATTEMPTS` = 2 (the suite-wide contract; no new mechanism).
* **Deterministic cases preserved:** the try-`i==1` special case (all-odd
  20-element prefix, the sentinel-semantics probe) targets attempt index 1 =
  the SECOND of 2 attempts — still deterministically reached (verified by
  the passing serial/omp/mpi/NDEBUG runs, which execute both attempts).
* **Stochastic coverage lost:** attempts 2–9 (eight additional
  unseeded-rand draws of the [1,100] fill) no longer run. **search38
  attempt normalization reduces stochastic validation coverage.** It is NOT
  claimed that 2 attempts have the same empirical fault coverage as 10; the
  suite-wide contract's known sensitivity limit (few deterministic
  unseeded-rand attempts can miss fault classes) now applies to 38 exactly
  as to every other benchmark. No new attempt policy was invented.
* **NEW FINDING (not in any frozen doc):** search/35 also hardcodes
  `numTries = 5`. The frozen D2.4 cost model documents only 38's exception,
  so its attempt table is incomplete for 35. NOT normalized here (no frozen
  target names 35); queued with a cost-model note (§28).

## 6. Sentinel / UB / boundary fixes (B2)

* **graph/19 — sentinel collapse.** Old: validate() mapped INT_MAX and
  EVERY negative value (both sides) to −1 before comparing — an alias set
  the prompt never states. Frozen target: exact family semantics (self = 0,
  unreachable = INT_MAX). New: the raw scalar comparison. Observable
  behaviour is unchanged for every input the current connected-graph
  generator produces (the reference is never INT_MAX/negative there —
  connectivity by construction); the alias mattered only for unreachable
  pairs. Regression: synthetic discriminator on a disconnected graph —
  oracle returns INT_MAX (frozen), candidate −1 now REJECTED, exact INT_MAX
  accepted, self distance 0 (probe, 4/4 green); end-to-end good candidate
  PASS serial/omp/mpi/NDEBUG.
* **histogram/20 — [0,255] tripwire.** Old: pattern-injected out-of-domain
  pixels reached `bins[image[i]]` unchecked → heap OOB write/SEGV inside
  the ORACLE, attributed to the sample (pilot: 2/20 specs lost). New:
  out-of-domain harness input → existing BI transport, trial skipped, no
  oracle call. Regression: pattern 6 run → authentic BI + PASS, ASan/UBSan
  clean (was ASan ERROR).
* **histogram/21 — [0,100] tripwire** (NaN-catching negated predicate);
  x == 100.0 stays IN domain (oracle clamp into bins[9] unchanged). Old:
  `static_cast<size_t>(x/10)` UB for negatives/huge/NaN. Regression:
  pattern 6 → BI, sanitizer-clean, also under `-DNDEBUG`.
* **histogram/24 — [0, 2^31) tripwire.** The frozen table domain (the
  negative-fraction semantics is BL-08, deliberately open — §16). Old:
  negatives silently swept into bins[0] (matches no prompt reading), ≥2^31
  cast UB. Regression: pattern 6 → BI, sanitizer-clean.
* **reduce/28 — v ≥ 0 ∧ v ≠ INT_MAX tripwire.** Frozen domain from the
  queued prompt contract + the catalogued INT_MAX sentinel collision. Old:
  such inputs graded unpinned conventions (negative parity) or the
  indistinguishable sentinel. Regression: pattern 6 (−O3-materialized
  INT_MIN/INT_MAX) → BI. Documented residue: the fill site's double→int
  conversion for pattern 6 is itself UB upstream of any guard (call-site
  typing; not frozen to change → queued to the enhanced/pattern wave; the
  tripwire neutralizes whatever values materialize).
* **scan/33 — |x| ≤ 100 tripwire** (D0-frozen bound keeping every suffix
  sum < 2^31). Old: pattern-6 at odd n → signed-overflow UB in the oracle.
  Regression: pattern 6 at n=7 → BI, UBSan-clean (was UBSan abort).
* **search/35 — n == 0 guard.** Frozen min_size 1; old: `rand() %
  pages.size()` → SIGFPE, a harness crash attributed to the sample. New:
  BI + return true. Regression: size 0 → BI, sanitizer-clean, also NDEBUG.
  The not-found sentinel stays structurally unreachable (forced-72 write)
  and untouched.
* **stencil/51 — [0,255] tripwire** (queued prompt contract; 9-tap int
  accumulation overflows above |v| = INT_MAX/16). Regression: pattern 6 →
  BI, sanitizer-clean (was signed-overflow UB).
* **histogram/23 — no code change:** the audit-listed empty-string OOB is
  unreachable under the current harness (fillRandString minLen 2 AND
  validate() overwrites every first character with `'a'+rand()%26`; no
  ENHANCED_FILL site) — verified in code; prompt sentence stays queued.

Sentinel design (B2.1): no benchmark return value was overloaded and no new
external API invented — all guards are validator-local and speak through
the EXISTING BI transport (B2.2); every guard is a plain `if`, NDEBUG-proven.

## 7. FFT07 top-level conjugation fix (B3.1)

`fftCooleyTookey` (the grading oracle, cpu.cc:78) was restructured exactly
as frozen (I12): the recursion — now `pareval_harness::
fftRecursionNoConjugate`, harness-local — computes the plain unnormalized
negative-exponent DFT with NO conjugation; the public `fftCooleyTookey`
applies the conjugation exactly ONCE at top level, INCLUDING N ≤ 1 (the
historical early return dropped it — the class-C N=1 defect closes with the
same fix). The oracle was NOT replaced, `correctFft` was NOT promoted to
grading, nothing conjugates twice; validate() and its 1e-3 componentwise
tolerance are untouched.

**Mandated verdict-inversion test (deterministic complex inputs where old
and fixed oracles differ):** candidate B (clean recursive DFT + one final
conjugation — the prompt-text shape that historically failed 1024/1024
cells) → **PASS**; candidate A (nested-conjugation replica of the
historical bug — historically the only passing shape) → **FAIL**. Both
end-to-end through the real driver.

## 8. FFT07 independent DFT verification (B3.1b)

Reference: the direct DFT sum formula per the frozen contract —
`conj( Σ_n x[n]·e^(−2πi·kn/N) )`, unnormalized — implemented in the probe
from the definition in `long double`; no repo FFT code, not `correctFft`,
not the repaired oracle, no candidate code. Input classes: impulse,
constant, real-asymmetric, complex-asymmetric, alternating — the
complex-asymmetric class separates forward/inverse sign, missing
conjugation and double conjugation uniquely; real-asymmetric separates
real-only artefacts; impulse/constant pin normalization and twiddle
convention.

| N | repaired vs independent DFT (max abs) | max rel | historical replica vs DFT (max abs) |
|---|---|---|---|
| 1 | 0.0 | 0.0 | 1.000e+00 (dropped conjugation) |
| 2 | 5.017e-20 | 2.5e-20 | 5.017e-20 (coincides at N=2, as documented) |
| 4 | 1.110e-16 | 2.0e-17 | 3.578e+00 |
| 8 | 3.553e-15 | 1.1e-16 | 2.902e+01 |
| 16 | 3.178e-14 | 1.2e-16 | 4.800e+02 |

The repaired oracle agrees with the independent reference to ≤ 3.2e-14
absolute (≤ 1.3e-16 relative) on every tested (N, class) — more than ten
orders inside the benchmark's 1e-3 componentwise comparator tolerance; the
historical behavior deviates by up to 4.8e+02, reproducing the audit's
magnitudes. **`FFT07 INDEPENDENT REFERENCE CHECK = PASSED`** — B3.1 may
count as closed; the productive oracle now computes the claimed operation.

## 9. FFT N=1 / shift guards (B3.2)

The Rosetta bit-reversal `>> (32 − m)` executed with m = 0 at N = 1
(shift-by-32 on a 32-bit type, formal UB; UBSan-verified per the FFT audit)
in: 05 `fft()` (on the grading path via `correctIfft`), 07 `correctFft`,
08 `correctFft`, 09 `correctFft`. Each site now skips the decimation for
N ≤ 1 (the bit-reversal of fewer than two elements is the identity — no
semantic change; the guard also removes 08's formal `log2(0)` cast at
N = 0 by never computing m there). No other FFT function carries the idiom
(fftCooleyTookey has no bit reversal). Regression: N = 1, 2 (smallest
further power of two) and 16 under ASan+UBSan for all four benchmarks —
12/12 clean PASS (N=1 was UBSan-flagged before); plus NDEBUG and omp/mpi
good-candidate runs.

## 10. sort40 validator (B4.1)

**Exact invariant set (frozen I10):** (1) output is a PERMUTATION of the
input — complex value multiset preserved exactly (values are verbatim
copies; sorted-lexicographic exact comparison via the shared
`reportAndCompareEq`, size-checked); (2) magnitudes non-decreasing
(`|out[i-1]| ≤ |out[i]|`, MISMATCH-reported). NO tie order demanded.
Additions: non-finite-component input → existing BI transport (a NaN
magnitude is an inconsistent comparator; outside the frozen primary value
domain); reference-sort selftest against the same invariants (BI on
violation — harness corruption, unreachable for std::sort). The oracle
call count is unchanged.

* Valid alternative outputs: stable_sort candidate PASSES — including on
  the all-tie `alternating` pattern input at n=64, where the historical
  element-wise validator provably failed it (BL-12 inversion, end-to-end).
* Invalid outputs: reversed order (multiset intact) FAIL; same-magnitude
  value replacement (order intact) FAIL; duplicated element (order intact)
  FAIL. §24 table.

## 11. sort42 validator (B4.2)

**Exact invariant set:** (1) `ranks` has size n and is a PERMUTATION of
0..n−1 (out-of-range and duplicates rejected, reported); (2) placing each
x[j] at position ranks[j] yields a non-decreasing sequence. NO tie order
demanded. Reference-ranking selftest (same invariants → BI on violation);
the verdict is now broadcast (the former root-only early `return false`
could diverge under MPI — repaired as part of the rewrite).

* Valid tie variants: descending-index tie-break candidate PASSES —
  including on the all-tie `all_same` pattern at n=1024, where the
  historical exact-equality validator graded libstdc++'s incidental
  permutation (measured 100% oracle≠stable at n ≥ 65536) — inversion
  demonstrated end-to-end.
* Invalid ranks: reversed positions (valid permutation, non-monotone) FAIL;
  duplicate rank FAIL; out-of-range rank FAIL. §24 table.

## 12. sort43 validator (B4.3)

**Exact invariant set:** (1) output is a PERMUTATION of the input records —
record multiset over (startTime, duration, value) exact (sorted by the
full field triple, field-wise `reportAndCompareEq`); (2) key `startTime`
non-decreasing. NO stable-sort requirement, NO tie-by-index. Reference
selftest as above.

* Tie freedom: stable_sort candidate PASSES at n=1024 (historically:
  disagreement with the unstable oracle in 500/500 trials at n ≥ 64 —
  inversion demonstrated end-to-end).
* Permutation checks: key inversion (records swapped across different
  keys) FAIL; record duplication/loss (keys still monotone) FAIL. §24.

## 13. geometry10 (B5.1)

**SET vs BOUNDARY-CYCLE determination — exact frozen evidence:** (a) the
structured frozen field reads verbatim "frozen family semantics: hull of
the DISTINCT POINT SET, collinear/single-point rules (I11)" — set language,
no cycle/order language anywhere in the frozen artifacts; (b) the queued
prompt contract says "Each hull vertex must appear exactly once in `hull`"
— a multiplicity rule, not an order rule; (c) the prompt itself asks for
"the SET of points that defined the smallest convex polygon"; (d) the
existing validator has always sorted both sides before comparing — order
was never part of the graded contract. → **SET SEMANTICS** is the frozen
output form; no boundary-cycle requirement was silently added or dropped
(none ever existed in the graded contract).

**Implementation:** the oracle now computes the hull of the DISTINCT point
set (sort + exact dedupe first): all-coincident input → that point ONCE
(historically twice — the audited size-2 "hull"); fewer than three
DISTINCT points → those distinct points; ≥3 distinct → monotone chain
(strict predicate, minimal vertex set — unchanged convention). The
validator (size + sorted exact-set comparison) is unchanged — it is
exactly the SET check.

**Degenerate cases (probe, production oracle):** all-identical(5) → 1
vertex; two-identical → 1; one point → itself; empty → empty; two distinct
→ both; collinear(4) → the two extremes; square + duplicated corner → 4;
square + edge midpoint → 4 (midpoint excluded); square + interior point →
4. 9/9 green.

## 14. geometry11 (B5.2)

Frozen K1 set-invariant semantics implemented in the oracle: distinct-set
dedupe; ≤1 distinct (incl. empty, all-coincident) → 0; exactly 2 distinct
→ 2·distance (the closed degenerate boundary — historically 0); ≥3
distinct collinear → 2·extent (the chain reduces to the two extremes and
the closing edge doubles the length — no special branch, verified);
otherwise the polygon perimeter (chain unchanged). The scalar validator
and its 1e-6 tolerance are untouched; the hull helper's semantics were
checked independently against the frozen distinct/collinear contract
(probe): BL-02 set-invariance pair {(0,0),(3,4)} vs {(0,0),(0,0),(3,4)} →
both 10 (historically 0 vs 10); one point → 0; all-coincident → 0; empty →
0; collinear(3) extent 10 → 20; unit square → 4 (also with duplicated
corner); 3-4-5 triangle → 12. 9/9 green. Tolerance boundary: candidate
+5e-7 → PASS, +2e-6 → FAIL.

## 15. histogram24 (B6)

The order's premise ("frozen decision: negatives remain valid, fractional
part = x − floor(x)") is NOT what the frozen artifacts say. The domain
table freezes the domain **0 ≤ v < 2^31** (special_conditions; the queued
prompt sentence reads "Assume every element of x is non-negative and
strictly smaller than 2147483648"), and the audit's BL-08 records the
negative-fraction semantics as "decision deliberately left open" with both
branches (restrict domain vs floor-based frac) explicitly open. Per the
source-of-truth rules the repository wins; no floor-semantics was
implemented and no domain was silently changed.

→ **B6 = QUEUED_NO_FROZEN_TARGET** for the fractional-part semantics
(exact missing decision: BL-08 branch choice), while the FROZEN part — the
0 ≤ v < 2^31 domain — is enforced by the B2 tripwire (out-of-domain
harness input → BI; UB path closed; no active inconsistency is presented
as "correct": in-domain, truncation and floor coincide and the oracle
matches the prompt).

## 16. scan34 (B7)

BL-10 (empty-subarray convention: K1 non-empty vs K2 empty-allowed) and
BL-11 (size-0 return INT_MIN) are both recorded as "decision deliberately
left open" with multiple live options; `oracle_change_queued: none`. No
frozen empty-subarray return semantics exists anywhere in the
source-of-truth documents. → **B7 = QUEUED_NO_FROZEN_TARGET** (`QUEUED —
FROZEN IMPLEMENTATION TARGET NOT SPECIFIED`); nothing implemented, no
convention chosen. Size 0 today is deterministic in practice on this
toolchain (documented in the table row) and the K1 oracle is a defensible
convention — no active inconsistency is reported as correct.

## 17. stencil50 (B8.1)

Oracle switched to the frozen 8-neighbor MOORE neighborhood (I4; the
literal `== 1` rule and dead-outside guards unchanged); validator switched
to FULL-vector exact comparison (I14) through the shared role-aware helper.
Not re-litigated — the frozen evidence is re-proven by the probe: the
prompt's documented 4×4 example reproduces EXACTLY (0/16 cells wrong;
historical 4-neighbor: 6/16 wrong), and the Moore-specific diagonal-pair
grid matches the hand-computed expectation (0/9 wrong). Regression: good
candidate PASS (serial/omp/mpi/NDEBUG; ASan N=0..3 clean — N=0 is a
defined vacuous empty comparison, no hang); 4-neighbor candidate (the
historical rule) FAIL; boundary-zeroing candidate FAIL (historically an
interior-window PASS at every size).

## 18. stencil52 (B8.2)

Full-vector validation incl. both boundary elements (1e-4 tolerance
unchanged; shared helper supplies size check + role-aware non-finite
semantics). The size_t-underflow window is gone with the window itself;
N = 0 (empty, defined) / 1 / 2 / 3 all sanitizer-clean; N = 1 and N = 2 are
no longer vacuous. Regression: good PASS everywhere; boundary-corrupting
candidate (−999999 at both ends — the audit's measured historical PASS)
now FAILS, including at N = 1.

## 19. stencil53 (B8.3)

Same as 52 in 2D: full flattened N×N output incl. the border ring (1e-6
unchanged). N = 0..3 sanitizer-clean; boundary-ring-corrupting candidate
(interior correct) now FAILS — historically 0 boundary cells were ever
compared.

## 20. stencil54 (B8.4)

Oracle verified to implement the frozen semantics already (all eight
neighbor reads guarded; out-of-grid contributes 0; no wrap) — unchanged.
Validator: full-grid exact comparison. Probe of frozen expectations: N=1
lone live cell dies (0 neighbors); 2×2 all-alive still life; 3×3 all-alive
→ 101000101; four-corners grid → all dead under dead-outside (a torus
keeps every corner alive — the discriminating case). Regression: TOROIDAL
candidate now FAILS (at 16 and 1024; historically accepted at every
measured size through the interior window); good candidate PASS everywhere;
N = 0..3 sanitizer-clean.

## 21. Additional B9 fixes

None. The all-60 structured-queue sweep (every `oracle_change_queued` /
`generator_change_queued` field) contains no further
`FROZEN_TARGET — IN WAVE 2B` entry: the remaining structured entries are
the Wave-2A-completed ones (45/46/47/48/49 constructions, 02/04/46
nonsquare, 41 k-fix, 38 OOB, 59 oracle) and prose `yes — …`
generator-capability entries that are ENHANCED_ONLY. Findings NOT
implemented because no frozen target exists (with their queues): 00
(BL-01), 34 (BL-10/11), 12/13/14 (BL-05/06/07 + degenerate-triple), 22
(axis convention), 36/37/39 (size-0/tie-break; the 35-vs-36/37/39 queue
asymmetry is documented), 35/`numTries=5` (new finding), 28 negative
parity, fill-typing UB at 28's call site, D6b adversarial-pattern rows.

## 22. Baseline-as-candidate matrix (B10.1)

Canonical correct candidates through the REAL driver path, authenticated
transport, for ALL 22 changed benchmarks (05 07 08 09 10 11 19 20 21 24 28
33 35 38 40 42 43 50 51 52 53 54): **serial 22/22 PASS, OpenMP 22/22 PASS,
MPI (real `mpirun -n 2`) 22/22 PASS** — exactly one authentic Validation
marker per launch, 0 BI. (One transient TEST-scaffold error: the 51_good
candidate initially lacked the prompt-supplied `edgeKernel` constant — a
candidate-authoring mistake, not a productive-code issue; fixed and both
affected cases rerun green: serial PASS, pattern-6 BI. All later 51 phases
in the main run already used the fixed candidate and were green.)

## 23. Negative discriminator matrix (B10.2)

| Case | Historical behavior | Expected now | Result |
|---|---|---|---|
| 07 nested-conjugation replica (candidate A) | PASS (only passing shape) | FAIL | ✓ |
| 07 prompt-text shape (candidate B) | FAIL (1024/1024) | PASS | ✓ |
| 19 candidate −1 for unreachable (synthetic, disconnected graph) | accepted (normalized) | rejected | ✓ probe |
| 20/21/24/28/33/51 pattern-6 out-of-domain input | OOB-SEGV / UB / unpinned grading | BI, sanitizer-clean | ✓ 6/6 |
| 35 size-0 | SIGFPE (harness crash) | BI | ✓ (also NDEBUG) |
| 40 stable-tie candidate on all-tie input | FAIL (BL-12) | PASS | ✓ |
| 40 reversed / value-replaced / duplicated | – | FAIL | ✓ 3/3 |
| 42 alt-tie-break candidate on all-same input | FAIL | PASS | ✓ |
| 42 reversed-ranks / duplicate-rank / out-of-range | – | FAIL | ✓ 3/3 |
| 43 stable_sort candidate | FAIL (500/500 at n≥64) | PASS | ✓ |
| 43 key-swap / record-duplicate | – | FAIL | ✓ 2/2 |
| 10 reversed-order hull | PASS (order never graded) | PASS | ✓ |
| 10 missing vertex / interior added / vertex replaced | – | FAIL | ✓ 3/3 |
| 11 tolerance +5e-7 / +2e-6 | – | PASS / FAIL | ✓ |
| 50 4-neighbor candidate | WAS the oracle | FAIL | ✓ |
| 50/52/53 boundary-wrong candidates | interior-window PASS | FAIL (52 also at N=1) | ✓ 4/4 |
| 54 toroidal candidate | accepted at every measured size | FAIL (N=16, 1024) | ✓ |
| 38 wrong index | – | FAIL | ✓ |

## 24. INVARIANT VALIDATOR COMPLETENESS (B10.6)

Positive equivalence first (B10.6.1): 40 stable-tie PASS (incl. all-tie
pattern input), 42 opposite-tie-break PASS (incl. all-same input), 43
stable_sort PASS, 10 reversed-order PASS — permissivity shown. Isolated
single-invariant violations (B10.6.2), each constructed from the correct
output so every OTHER invariant holds:

| Benchmark | Invariant | Isolated violating output | Other invariants preserved? | Expected | Actual |
|---|---|---|---|---|---|
| sort40 | magnitudes non-decreasing | correct sort, then reversed | multiset exactly preserved | FAIL | FAIL ✓ |
| sort40 | multiset preserved | correct sort, then x[0] := −x[0] (same magnitude) | order still non-decreasing | FAIL | FAIL ✓ |
| sort40 | multiset preserved (dup/loss) | correct sort, then x[0] := x[1] | order still non-decreasing | FAIL | FAIL ✓ |
| sort42 | application non-decreasing | position-reversed ranks | still a valid permutation | FAIL | FAIL ✓ |
| sort42 | permutation (uniqueness) | ranks[0] := ranks[1] | rest is the correct ranking | FAIL | FAIL ✓ |
| sort42 | permutation (range) | ranks[0] := n | rest correct | FAIL | FAIL ✓ |
| sort43 | key non-decreasing | two different-key records swapped | record multiset exact | FAIL | FAIL ✓ |
| sort43 | record multiset | record[0] := record[1] | keys still non-decreasing | FAIL | FAIL ✓ |
| geometry10 (SET) | no missing vertex | correct set minus one vertex | remaining vertices correct | FAIL | FAIL ✓ |
| geometry10 (SET) | no spurious point | correct set plus interior centroid | hull vertices all present | FAIL | FAIL ✓ |
| geometry10 (SET) | exact vertex set | one vertex replaced by the centroid (size preserved) | count correct | FAIL | FAIL ✓ |

Degenerate invariants (B10.6.3) for geometry10/11: duplicates irrelevant,
one distinct point, two distinct points, collinear ≥3, normal polygon —
all probed against the production oracles (§13/§14; 18/18 green).
geometry11's validator is a plain scalar comparison (no structural
invariants) → per the contract it enters B10.6 only via its oracle-helper
checks above.

Every necessary invariant discriminates in isolation:
**`INVARIANT SET COMPLETE FOR TESTED CONTRACT` — B10.6 = PASSED.**

## 25. Serial / OpenMP / MPI matrix (B10.4)

§22: 22/22/22 across the three execution models, real `mpirun -n 2`,
exactly one authentic marker per launch, no rank-divergent verdict (42's
former root-only early return — a latent MPI divergence — was replaced by
the standard broadcast pattern as part of the validator rewrite).

## 26. ASan / UBSan / NDEBUG results (B10.3)

* ASan+UBSan: FFT 05/07/08/09 at N = 1/2/16 → 12/12 clean PASS (N=1
  historically UBSan-flagged); tripwire benchmarks 20/21/24/33/51 with
  pattern 6 and 35 at size 0 → 6/6 clean BI (historically SEGV/UB);
  stencils 50/52/53/54 at N = 0/1/2/3 → 16/16 clean.
* NDEBUG: 22/22 good candidates PASS; guard paths re-proven under NDEBUG
  (21 pattern-6 → BI; 35 size-0 → BI). No new guard exists only as
  `assert`.
* 28's pattern-6 UBSan caveat: the remaining UB sits in the FILL call site
  (double literals into an int container), upstream of any validator guard
  — documented and queued (§21); the tripwire neutralizes the materialized
  values (measured BI at −O3).

## 27. Existing regression suites (B10.5)

Real Python 3.8.20 (pareval-py38): `test_comparator_semantics` (all checks
passed), `test_evaluation` 27, `test_enhanced` 11 groups, `test_feedback`
8, `test_orchestrator` 12 groups, `test_backfill` 7 groups, `test_overview`
7 groups, `test_generation` 10 groups, `test_cleaning` 13; `compileall`
over the whole pipeline rc = 0. No Python production code changed; the 3.8
contract holds. **Overall B10 tally: 165/165 checks green** (163 in the
master log + the 2 rerun 51-scaffold cases).

## 28. Validation / cost-impact audit (B11)

I3 unchanged: the 10-s budget stays per ONE serial oracle call; whole
`validate()` calls may cost more.

| Benchmark | Oracle calls before → after (per validate) | Attempts before → after | Asymptotic delta | Measured validate wall (serial good, quiet host) |
|---|---|---|---|---|
| 38 | 10 → 2 | 10 → 2 | −80% validation work | 0.016 s @4096 |
| 35 | 5 → 5 (+O(1) guard) | 5 → 5 (NEW: undocumented — cost-model note) | none | – |
| 07 | 2 → 2 (oracle internally cheaper: no per-level conj loops) | 2 → 2 | none | 0.021 s @1024 |
| 40 | 2 → 2 (selftest reuses the same call) | 2 → 2 | +O(n log n) sorts per check | 0.021 s @4093 |
| 42 | 2 → 2 | 2 → 2 | +O(n) perm check +O(n log n) alt path | 0.013 s @4096 |
| 43 | 2 → 2 | 2 → 2 | +O(n log n) | 0.022 s @4096 |
| 10 | 2 → 2 | 2 → 2 | +O(n log n) dedupe | 0.011 s @1024 |
| 11 | 2 → 2 | 2 → 2 | +O(n log n) dedupe | 0.011 s @4096 |
| 50 | 2 → 2 (Moore ≈ 1.6× oracle constant, frozen-measured; full-vector compare O(N²) instead of interior) | 2 → 2 | constant factor | 1.670 s @4096 |
| 52/53/54 | 2 → 2 | 2 → 2 | boundary cells added to the compare | 0.013 s @4096 / 0.804 s @4093 / 3.523 s @8192 |
| 19/20/21/24/28/33/51 | unchanged (+O(n) tripwire scan) | unchanged | +O(n) | 0.462 s @4096 (19) |

All measured validate() walls are far inside any budget; no serial oracle
call moved. The D2.4 full-run model changes in two small, sourced ways: 38's
documented ×10 attempt exception disappears (cost DOWN), and 35 carries a
previously undocumented ×5 exception (cost UP vs the model's assumption of
2). Neither is domain-relevant, but the model's attempt table is now known
to be incomplete → **`QUEUED — workload model refresh required`** for the
Reporting/Provenance wave. S/M/L untouched. The B3.1b DFT reference is
test-scratch only and adds no productive cost.

## 29. Prompt-diff queue (B12) — nothing edited

| Prompt/benchmark | Required frozen text change | Why | Requires regeneration after Prompt Wave? |
|---|---|---|---|
| stencil50 | 8-neighbor Moore statement (I4) | oracle now Moore; prompt silent | yes (samples) |
| fft06 | forward DFT, negative exponent, unnormalized + example signs | example/oracle sign conflict (decision direction per frozen I12 family convention) | yes |
| fft05/07/08/09 | "N is always a power of two" | radix-2-only baselines, unrestricted prompts | yes |
| fft07 | example correction (conjugated values) | example shows the UNconjugated transform vs the now-correct conj(DFT₋) oracle | yes |
| fft09 | example typo (−2.42421 → −2.41421) | documented single-value typo | yes |
| sort41 | 1-indexed multiset k + corrected example | frozen k-domain; example matches no oracle reading | yes |
| sort42 | tie/rank semantics sentence + corrected example 2 ([4,0,2,3,1]) | I10 validator admits all valid tie permutations; example arithmetically impossible | yes |
| sort40 | (superseded restriction) — distinct-magnitude sentence NOT needed any more under I10; no prompt change required | validator now tie-tolerant | n/a |
| sort43 | stable-sort sentence NOT needed under I10 | validator tie-tolerant | n/a |
| sparse45/46/47/49 | unique (row,column) COO statement | frozen I5 contracts implemented in 2A | yes |
| sparse48 | unique-index statement | I5 | yes |
| sparse45 | square + nonsingular statement | D4 | yes |
| sparse49 | no-pivot-valid + dense row-major output form | D5 | yes |
| histogram20 | (already stated [0,255]) — no change | tripwire matches prompt | n/a |
| histogram21 | 100 → bins[9] inclusive-upper sentence + bins zero-init | boundary rule unpinned | yes |
| histogram24 | frozen domain sentence "non-negative and < 2^31" | table-frozen domain now enforced by tripwire | yes |
| histogram22 | axis/origin convention sentence | open decision; PROMPT_ONLY | pending decision |
| histogram23 | "every string is non-empty" | precision fix | yes (low priority) |
| scan34 | frozen empty-subarray convention — PENDING BL-10/11 decision | no frozen text exists yet | pending decision |
| scan28 | "non-negative; no odd → INT_MAX" | queued contract behind the tripwire | yes |
| scan33 | value bound \|x\| ≤ 100 (spec-side alternative possible) | tripwired frozen domain | yes |
| stencil51 | grayscale [0,255] guarantee | tripwired frozen domain | yes |
| geometry10/11 | duplicate/collinear/one-point semantics + edge-point rule (+ coordinate-magnitude sentence OR predicate decision) | I11 semantics now implemented | yes |
| stencil52/53/54 | boundary semantics now graded (52/53 zero-padding already stated; 54 needs "out-of-grid dead, no wrap") | full-vector validation | yes (54); 52/53 text already present |
| graph19 | symmetric/unit-edge/self=0/unreachable=INT_MAX sentence | sentinel semantics now exact | yes |
| search38 | no-even → x.size() sentence | sentinel convention | yes |
| geometry12/13/14, search37 | n<3/n<2/tie-break sentences | pending decisions (BL-05/07 etc.) | pending decision |

## 30. benchmark_shapes consistency (B13)

`derive_shapes.py --check` after all Wave-2B edits: **"stored shapes match
the derivation."** No Wave-2B change added or removed an ENHANCED_FILL
site, so the artifact regenerated in Wave 2A remains exact. **B13 =
CONSISTENT** (no regeneration needed, nothing else written). Known,
explained metadata note carried forward: the domain table's OWN
implementation-state fields are now stale where waves 2A/2B implemented
queued items (59 oracle "REQUIRED", 07 conjugation, I10/I11/I4/I14
entries, sentinel/UB queue) — the table is semantically frozen/read-only;
this report and the Wave-2A report are the provenance until the
Reporting/Provenance wave refreshes the metadata.

## 31. Candidate-independence / helper-collision audit (B14 items 9/10)

No trusted path computes an expected result via a candidate symbol (the
only candidate-visible dependency remains 51's prompt-supplied `edgeKernel`
constant — prompt-provided data, unchanged and pre-existing). All new
namespace-level helpers live in `pareval_harness`
(`fftRecursionNoConjugate`; 40's `magnitudesNonDecreasing`/
`sameComplexMultiset`/`validSortByMagnitude`; 42's `validRanks`; 43's
`recordLess`/`keysNonDecreasing`/`sameRecordMultiset`/
`validSortByStartTime`). Zero new global-namespace symbols; `fftCooleyTookey`
keeps its pre-existing name. Grep-verified: `namespace pareval_harness` in
exactly the 7 Wave-2A files + 4 Wave-2B files.

## 32. Changed-file list

23 productive files (4 fft baseline.hpp, 2 geometry baseline.hpp, 1
stencil50 baseline.hpp, 16 cpu.cc: 19, 20, 21, 24, 28, 33, 35, 38, 40, 42,
43, 50, 51, 52, 53, 54) — §37/§38 for the exact stat. All test candidates,
probes and logs live outside the repository (session scratchpad `w2b/`).

## 33. Per-gate status table

| Gate | Status |
|---|---|
| B0 queue extraction | **COMPLETE** |
| B1 search38 attempts | **IMPLEMENTED** |
| B2 sentinel/UB fixes | **IMPLEMENTED** |
| B3 FFT code fixes | **IMPLEMENTED** |
| B3.1b FFT07 independent reference | **PASSED** |
| B4 sort validators | **IMPLEMENTED** |
| B5 geometry validators | **IMPLEMENTED** |
| B6 histogram24 | **QUEUED_NO_FROZEN_TARGET** (fraction semantics; frozen-domain tripwire implemented under B2) |
| B7 scan34 | **QUEUED_NO_FROZEN_TARGET** |
| B8 stencil family | **IMPLEMENTED** |
| B9 remaining frozen queue | **COMPLETE** |
| B10 regression | **PASSED** (165/165 + 9/9 py3.8 suites) |
| B10.6 invariant-validator completeness | **PASSED** |
| B11 cost-impact audit | **DOCUMENTED** (+ workload-model refresh queued) |
| B12 prompt queue | **COMPLETE** |
| B13 metadata consistency | **CONSISTENT** |
| B14 scope audit | **PASSED** |

## 34. CUMULATIVE pilot_001 vs pilot_002 comparability audit

Union of the Domain Approval Wave + Wave 2A + Wave 2B, all 60 benchmarks;
each benchmark counted ONCE. Categories: A input construction, B
validator/oracle semantics, C size domain, D additional validation cases.

**Cumulative affected: 29 of 60 benchmarks (48.3%).** Unaffected (F — no
material comparability change): 31, including 05/08/09 (formal-UB guards
with bit-identical outputs), 35 (crash→marker, same
baseline_incompatible class downstream), 00/01/03/06/13–18/22/23/25/27/
29–32/34/36/37/39/44/55/56/57/58 and 60-th row 42's sibling 44 etc.

| Benchmark | Input construction | Validator/oracle | Size | Additional cases | Pure pilot comparison still valid? |
|---|---|---|---|---|---|
| 02 | – | – | – | ✓ nonsquare | no (caveat) |
| 04 | – | – | – | ✓ nonsquare | no (caveat) |
| 07 | – | ✓ conjugation fix | ✓ M 65536→32768 | – | no |
| 10 | – | ✓ distinct-set oracle | – | – | no |
| 11 | – | ✓ K1 set-invariant | – | – | no |
| 12 | – | – | ✓ L 2048→1024 | – | no |
| 19 | ✓ per-attempt reset | ✓ sentinel exact | – | – | no |
| 20 | – | ✓ tripwire (crash→BI) | – | – | no |
| 21 | – | ✓ tripwire | – | – | no |
| 24 | – | ✓ tripwire | – | – | no |
| 26 | – | ✓ D6 comparator | ✓ M/L | – | no |
| 28 | – | ✓ tripwire | – | – | no |
| 33 | – | ✓ tripwire | – | – | no |
| 38 | ✓ OOB fix (<20) | – | – | ✓ attempts 10→2 (coverage REDUCED) | no |
| 40 | – | ✓ invariant validator | – | – | no |
| 41 | ✓ k ∈ [1,n] | – | – | – | no |
| 42 | – | ✓ invariant validator | – | – | no |
| 43 | – | ✓ invariant validator | – | – | no |
| 45 | ✓ D4 construction | ✓ graded vs x_gen | – | – | no |
| 46 | ✓ unique coords | ✓ tripwire | – | ✓ nonsquare | no |
| 47 | ✓ unique coords | ✓ tripwire | – | – | no |
| 48 | ✓ unique indices | ✓ tripwire | – | – | no |
| 49 | ✓ D5 construction | ✓ graded vs L/U truth | – | – | no |
| 50 | – | ✓ Moore + full-vector | – | – | no |
| 51 | – | ✓ tripwire | – | – | no |
| 52 | – | ✓ full-vector | – | – | no |
| 53 | – | ✓ full-vector | – | – | no |
| 54 | – | ✓ full-vector | – | – | no |
| 59 | – | ✓ independent oracle | – | – | no |
| all other 31 | – | – | – | – | yes |

Per-category counts over the 29: A = 8 (19, 38, 41, 45, 46, 47, 48, 49);
B = 24; C = 3 (07, 12, 26); D = 3 (02, 04, 46) plus 38's attempt
REDUCTION; E (≥2 categories) = 9 (07, 19, 26, 38, 45, 46, 47, 48, 49).
Overlaps: the sparse family carries A+B (46 additionally D); 07/26 carry
B+C.

**Suite-level judgment.** With 29/60 benchmarks affected — including
complete families (sparse_la 5/5, stencil 50–54 5/5, sort 40–43 4/4
counting 41, histogram 3/5, fft 1/5 materially) and with the dominant
change class being VALIDATOR/ORACLE SEMANTICS (24 of 29) — an aggregate
statement like "pilot_002 improved over pilot_001" is **methodically NOT
directly interpretable at suite level**: it confounds model/pipeline change
with benchmark/validator change, in both directions (validators became
stricter where they were vacuous — full-vector stencils, fft07, 59 — and
more permissive where they were wrongly strict — sort ties, 40/42/43;
input distributions changed for the sparse family). Comparisons that remain
methodically sound: (1) the 31-benchmark UNCHANGED subset for aggregate
before/after deltas; (2) per-benchmark before/after with the per-wave
provenance annotation of this table; (3) regression-evidence statements
(the verdict-inversion pairs above document exactly which verdict classes
flip for reasons unrelated to model quality); (4) within-pilot_002 model
comparisons (all models face identical benchmarks). Additional cross-wave
note for the Reporting/Provenance wave: the Wave-1/1b comparator/transport
semantics (BI vocabulary, size-mismatch FAIL, non-finite-candidate FAIL)
predate this union and additionally affect ALL 60 relative to pilot_001.
pilot_001 itself remains unchanged (read-only).

## 35. Queued items after Wave 2B

**A) ATOMIC PROMPT WAVE:** the full §29 table (stencil50 Moore, FFT06
convention + FFT power-of-two + 07/09 example fixes, sort41/42 semantics +
examples, sparse unique contracts + D4/D5 statements, histogram21/24
sentences, scan28/33 domains, geometry10/11 semantics, stencil54
dead-outside, graph19 contract, search38 sentinel, plus the
pending-decision sentences 22/34/12/13/14/37).

**B) ENHANCED PATTERN/HARNESS WAVE:** sparse45/49 pattern mappings;
fill_effect + implementation-state metadata refresh (incl. the stale
"queued" fields this wave completed); adversarial pattern policy for the
D6b value-domain rows (40/52/55/56/58/59) and the tripwired rows; 28's
fill-typing UB; >4096 per-benchmark support; NO_FILL_SITE variation
(15–19, 23, 25, 44, 45); spec regeneration (blocked until then:
final enhanced gate, pilot_002).

**C) DEDICATED TIMING WAVE:** sparse45/49 timed constructions; graph19
timing accumulation; sparse-family timed duplicate inputs; no new
timing-only findings surfaced in 2B.

**D) STATIC/REPAIR WAVE:** GCC analyzer event path, tool-state model,
PARCOACH, LLOV gate, retry semantics (untouched).

**E) ASSEMBLY WAVE:** comment dedup, balance rollback, prose/backtick leak,
assembly-side namespace-collision safety (untouched).

**F) REPORTING/PROVENANCE/REGRESSION WAVE:** workload-model refresh (§28:
38's exception gone, 35's ×5 newly documented); cumulative pilot
comparability (§34) incl. the Wave-1 transport note; historical
vacuous-pass correction; final all-60 consistency + domain-table metadata
refresh; provenance snapshots.

## 36. Items completed here that MUST NOT be reopened

The B1 attempt normalization; the B2 guards/tripwires (19 sentinel, 20, 21,
24, 28, 33, 35, 51); the fft07 top-level conjugation oracle + its B3.1b
verification; the fft 05/07/08/09 N≤1 shift guards; the I10 invariant
validators of 40/42/43 (with their B10.6-proven invariant sets); the I11
distinct-set oracles of 10/11; the I4/I14 stencil oracle+validators of
50/52/53/54 — unless new code changes their premises, stored evidence is
refuted, or the user explicitly reopens them.

## 37. `git diff --stat`

```
 .../benchmarks/fft/05_fft_inverse_fft/baseline.hpp |  35 ++---
 .../fft/07_fft_fft_conjugate/baseline.hpp          |  66 +++++++---
 .../benchmarks/fft/08_fft_split_fft/baseline.hpp   |  35 ++---
 .../fft/09_fft_fft_out_of_place/baseline.hpp       |  33 +++--
 .../geometry/10_geometry_convex_hull/baseline.hpp  |  26 +++-
 .../11_geometry_convex_hull_perimeter/baseline.hpp |  35 +++--
 .../benchmarks/graph/19_graph_shortest_path/cpu.cc |  19 +--
 .../histogram/20_histogram_pixel_histogram/cpu.cc  |  22 ++++
 .../histogram/21_histogram_bin_0-100/cpu.cc        |  23 ++++
 .../histogram/24_histogram_count_quartile/cpu.cc   |  24 ++++
 .../reduce/28_reduce_smallest_odd_number/cpu.cc    |  25 ++++
 .../scan/33_scan_reverse_prefix_sum/cpu.cc         |  22 ++++
 .../35_search_search_for_last_struct_by_key/cpu.cc |  11 ++
 .../38_search_find_the_first_even_number/cpu.cc    |  10 +-
 .../cpu.cc (sort/40_…_by_magnitude)                | 108 ++++++++++++++--
 .../benchmarks/sort/42_sort_sorted_ranks/cpu.cc    |  92 ++++++++++++-
 .../43_sort_sort_an_array_of_structs_by_key/cpu.cc | 142 +++++++++++++++------
 .../stencil/50_stencil_xor_kernel/baseline.hpp     |  10 ++
 .../stencil/50_stencil_xor_kernel/cpu.cc           |  20 +--
 .../stencil/51_stencil_edge_kernel/cpu.cc          |  22 ++++
 .../52_stencil_1d_jacobi_3-point_stencil/cpu.cc    |  19 +--
 .../53_stencil_2d_jacobi_5-point_stencil/cpu.cc    |  19 +--
 .../stencil/54_stencil_game_of_life/cpu.cc         |  20 ++-
 23 files changed, 647 insertions(+), 191 deletions(-)
```

## 38. `git status --porcelain`

```
 M drivers/cpp/benchmarks/fft/05_fft_inverse_fft/baseline.hpp
 M drivers/cpp/benchmarks/fft/07_fft_fft_conjugate/baseline.hpp
 M drivers/cpp/benchmarks/fft/08_fft_split_fft/baseline.hpp
 M drivers/cpp/benchmarks/fft/09_fft_fft_out_of_place/baseline.hpp
 M drivers/cpp/benchmarks/geometry/10_geometry_convex_hull/baseline.hpp
 M drivers/cpp/benchmarks/geometry/11_geometry_convex_hull_perimeter/baseline.hpp
 M drivers/cpp/benchmarks/graph/19_graph_shortest_path/cpu.cc
 M drivers/cpp/benchmarks/histogram/20_histogram_pixel_histogram/cpu.cc
 M drivers/cpp/benchmarks/histogram/21_histogram_bin_0-100/cpu.cc
 M drivers/cpp/benchmarks/histogram/24_histogram_count_quartile/cpu.cc
 M drivers/cpp/benchmarks/reduce/28_reduce_smallest_odd_number/cpu.cc
 M drivers/cpp/benchmarks/scan/33_scan_reverse_prefix_sum/cpu.cc
 M drivers/cpp/benchmarks/search/35_search_search_for_last_struct_by_key/cpu.cc
 M drivers/cpp/benchmarks/search/38_search_find_the_first_even_number/cpu.cc
 M drivers/cpp/benchmarks/sort/40_sort_sort_an_array_of_complex_numbers_by_magnitude/cpu.cc
 M drivers/cpp/benchmarks/sort/42_sort_sorted_ranks/cpu.cc
 M drivers/cpp/benchmarks/sort/43_sort_sort_an_array_of_structs_by_key/cpu.cc
 M drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/baseline.hpp
 M drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/cpu.cc
 M drivers/cpp/benchmarks/stencil/51_stencil_edge_kernel/cpu.cc
 M drivers/cpp/benchmarks/stencil/52_stencil_1d_jacobi_3-point_stencil/cpu.cc
 M drivers/cpp/benchmarks/stencil/53_stencil_2d_jacobi_5-point_stencil/cpu.cc
 M drivers/cpp/benchmarks/stencil/54_stencil_game_of_life/cpu.cc
?? thesis/evaluation/wave2b_benchmark_validator_implementation_report.md
```

No commit, no `git add`.

## 39. Final classification

All B15.3 conditions hold: B0 COMPLETE; every real `FROZEN_TARGET — IN
WAVE 2B` entry implemented; B1–B9 without open technical blocker (B6/B7 are
admissible QUEUED_NO_FROZEN_TARGET per B15.1 — the missing decisions are
provably not frozen, no new semantics was invented, and no productive
validation path presents a known-wrong result as correct); FFT07 was
changed and B3.1b = PASSED; B10 = PASSED; B10.6 = PASSED for every new
invariant validator; B11 = DOCUMENTED; B12 = COMPLETE; B13 = CONSISTENT;
B14 = PASSED.

**WAVE 2B COMPLETE.**

This does NOT mean: prompts changed, Enhanced Wave complete, Timing Wave
complete, Static/Repair complete, Assembly complete, or pilot_002 approved.
