# Measurement definitions — what the validation numbers actually mean

Analysis of the scoring semantics behind `results/metrics.csv`,
`results/overlap.csv` and `results/summary.md`. This is the reference for
the thesis methodology chapter. Code under discussion:
`score_validation.py`, `suite_kernels.py`, `cwe_map.py`.

## 1. Label granularity per suite

| Suite | Label says THAT a defect exists | Label says WHICH defect | Used by the scorer? |
| --- | --- | --- | --- |
| Juliet | yes (bad/good compile variant via `OMITGOOD`/`OMITBAD`) | yes — the CWE class from the testcase directory (e.g. `CWE415`) | **yes**: TP requires a check_id mapped to that CWE class |
| DRB | yes (`-yes.c` / `-no.c` filename) | partially — the filename carries the race *mechanism* (e.g. `antidep1`, `lastprivatemissing`), but all bad kernels share the single defect category *data race* | mechanism is **not** parsed (single category makes it redundant for TP-matching); label used as bad/good only |
| MBI | yes (`\| ERROR:` vs `\| OK` in the `BEGIN_MBI_TESTS` header) | yes — 26 error categories (e.g. `CallMatching`, `MissingWait`, `InvalidDatatype`), parsed into `classes` | parsed, but the **lax** TP view ignores it; the **strict** view (`tp_strict`) uses it |

## 2. TP definition per suite

- **Juliet — type-aware.** A finding is a TP only if its check_id is in the
  CWE class's per-tool prefix list (`JULIET_MATCHERS`). Unrelated findings
  on a bad kernel (style noise, incidental leaks) do not count. The mapping
  is deliberately conservative and was calibrated empirically
  (`calibrate_cwe_map.py`); empty entries are honest zeros.
- **DRB — category-equivalent.** Any race-family finding counts
  (`DRB_RELEVANT`). Since *data race* is the only defect category in the
  suite, this file-level rule is identical to category-aware matching.
- **MBI — lax by default, strict as an additional view.** The lax view
  counts any defect-identifying finding of the tool's family (capability
  markers like `must-unsupported` excluded via `NON_FINDINGS`). It is
  category-blind: e.g. `must-leak-comm` on a kernel labeled
  `communicatormatching` counts as lax TP. The additional
  `tp_strict`/`recall_strict` columns require the finding to *identify* a
  labeled category, via the `MBI_STRICT` mapping (grounded in the empirical
  category x check_id matrix of the full run plus documented tool
  semantics; deadlock reports count for root causes that manifest as
  deadlock, mirroring MBI's own expected-outcome model).

Measured effect of strict vs lax (full run): `must` 0.837 → 0.835 recall
(923 of its 926 lax TPs identify the labeled category — MUST's reports are
essentially category-faithful), `parcoach` 0.600 → 0.575 (28 kernels are
symptomatic hits: collective-ordering warnings on `messagerace` kernels,
which the method cannot identify as races), `clang_sa`/MPI-Checker
0.287 → **0.011** (its single opaque check_id fires broadly across 12
categories, but only the request-lifecycle family is identified by design —
the lax 0.287 is almost entirely category-blind co-occurrence).

## 3. Overlap semantics

`overlap.csv` counts on **kernel level**: `both` means both tools produced
at least one class-relevant finding **on the same bad kernel** — not that
they reported the same defect at the same location.

How far apart can the readings be?
- **Juliet:** one kernel = one planted CWE instance; kernel-level closely
  approximates bug-level.
- **DRB:** kernels carry exactly one labeled race. Line-level sample (5
  kernels with TP from both tsan and llov): 3/5 report the identical line,
  2/5 adjacent lines (±2 — access- vs. loop-granularity of the two
  methods). Kernel-level is a good proxy here.
- **MBI:** kernels carry one labeled defect, but tools may report different
  manifestations (deadlock vs. leak of the same root cause); overlap reads
  as "both flagged the kernel", which is the operationally relevant
  question for tool redundancy in a repair loop.

## 4. The clang_tidy_ast zeros

Verified against the raw JSONLs (0 TP on Juliet and MBI):
- **Juliet:** AST-side findings on bad kernels are exclusively
  scaffold/style noise (`bugprone-macro-parentheses`,
  `bugprone-reserved-identifier`, `concurrency-mt-unsafe` on `rand()`,
  `misc-const-correctness`, `bugprone-narrowing-conversions` on scaffold
  loop counters — narrowing is a different defect than the planted
  arithmetic overflow of CWE190/191). No observed check_id justifies a
  mapping; the zero is genuine.
- **MBI:** the mapping (`mpi-*`) is non-empty, but zero `mpi-*` findings
  occurred across 1,871 kernels: the AST MPI checks detect literal
  same-statement errors, MBI's defects are cross-call/cross-rank. The
  path-sensitive MPI-Checker (`clang_sa`) fires on the same rows.

**Scope note:** this zero holds for THESE synthetic suites' defect
classes. AST checks (bugprone-*, openmp-*) target programming slips that
the suites do not measure; the result must not be generalized to "AST
matchers are useless".

## 5. Not part of any metric

`skipped` (kernel does not compile here) and `errors` (tool failure:
timeout, crash, missing report) are excluded from all metrics — a tool
failure is not a negative result. Dynamic tools (asan_ubsan, memcheck,
tsan*, must) only detect what the test execution triggers; their recall is
not directly comparable to static tools' recall.
