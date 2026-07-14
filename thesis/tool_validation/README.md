# Tool Validation (Overlap Measurement)

One-time measurement to **justify the tool selection** — not part of the
thesis results and deliberately **not** integrated into the evaluation
pipeline. The selected analysis tools run against three labeled benchmark
suites; per tool we measure recall, false-positive rate, precision, F1, and
the pairwise overlap between tools.

| Suite | Tools | Labels |
| --- | --- | --- |
| Juliet C/C++ 1.3 (NIST SARD), memory/pointer/overflow CWE subset | compiler, clang_tidy (scored as the virtual tools clang_sa + clang_tidy_ast), cppcheck, infer — plus the executed-runtime tools asan_ubsan and memcheck | bad/good per testcase (OMITGOOD/OMITBAD), CWE class from the path |
| DataRaceBench (LLNL) | llov, parcoach, tsan — plus justification measurements: helgrind, drd (NOT pipeline tools; the measurement documents their exclusion) and tsan_noarcher (quantifies Archer's contribution) | `-yes.c` (race) / `-no.c` (race-free) in the file name |
| MBI (MPI Bugs Initiative) | clang_tidy (MPI-Checker, scored as clang_sa/clang_tidy_ast), parcoach, must | `BEGIN_MBI_TESTS` header (`| OK` / `| ERROR: <class>`) |

The tools run **exactly in their pipeline configuration** (same check sets,
flags, parsers, fail-safe semantics — imported from
`thesis/evaluation/tools.py` / `dynamic_tools.py`), but directly on the
standalone suite kernels instead of the ParEval driver scaffold (design
decision documented in `validation_tools.py`).

## Workflow

```sh
# 1. Fetch the suites (once; lands in suites/, gitignored)
python3 thesis/tool_validation/setup_suites.py

# 2. Runner per container (results: results/<suite>/<tool>.jsonl).
#    Resume is the default — reruns skip already-processed kernels;
#    use --restart to start over. --limit N is stratified (N/2 bad + N/2 good).
#    Main container (pareval-thesis):
python3 thesis/tool_validation/run_validation.py --suite juliet \
    --tools compiler clang_tidy cppcheck infer asan_ubsan memcheck
python3 thesis/tool_validation/run_validation.py --suite drb \
    --tools tsan tsan_noarcher helgrind drd
python3 thesis/tool_validation/run_validation.py --suite mbi --tools clang_tidy must
#    PARCOACH container (parcoach-demo:2.4.1):
python3 thesis/tool_validation/run_validation.py --suite drb --tools parcoach
python3 thesis/tool_validation/run_validation.py --suite mbi --tools parcoach
#    LLOV container (pareval-llov):
python3.8 thesis/tool_validation/run_validation.py --suite drb --tools llov

# Smoke: --limit 20   Canary check: --only <kernel-id-substring>

# 3. Scorer (reads results/, writes results/summary.md + CSVs)
python3 thesis/tool_validation/score_validation.py
```

## Juliet subset

`--juliet-per-class` (default 50) caps the testcase files per CWE class —
the deterministic, alphabetically first N single-file testcases per class
(13 classes × 50 files × bad+good = 1,300 kernels). The full suite (37,838
kernels) multiplies runtime without adding statistical value for an overlap
measurement. Multi-file testcases (letter-suffixed) and Windows-only cases
are excluded by design.

## Interpretation

- **Recall** = TP / (TP+FN) over bug-labeled kernels (matching: Juliet by
  the CWE class of the finding via `cwe_map.py`; DRB/MBI file-level with a
  per-tool relevance filter).
- **FP rate** = FP / (FP+TN) over correct-labeled kernels.
- **Precision** = TP / (TP+FP), **F1** = harmonic mean.
- Kernels that do not compile are logged as `skipped` and excluded from all
  metrics; tool failures are `errors`, likewise excluded.
- **Dynamic-tool semantics:** asan_ubsan/memcheck (Juliet) and
  tsan/tsan_noarcher (DRB) only report a bug the test run actually
  triggers. Their recall is not directly comparable to static tools.
- **Virtual tools:** `clang_sa` (clang-analyzer-*) and `clang_tidy_ast` are
  the method-level split of ONE clang-tidy invocation (symbolic execution
  vs. AST matchers) — no separate run. Rationale: redundancy in the thesis
  is defined over detection methods, and clang-tidy bundles two of them.
- **Justification measurements** (not pipeline tools): helgrind/drd document
  their exclusion suite-wide; tsan_noarcher (TSan without the Archer OMPT
  plugin) quantifies Archer's FP suppression inside the OpenMP runtime.
- **Known honest results** (verified, not harness artifacts): PARCOACH
  finds nothing on DRB data races (it is a collective verifier; its binary
  exposes no OpenMP mode) and produces genuine FPs on MBI's rank-conditional
  but correct collectives (static over-approximation) — both are
  measurement results for the methodology chapter, not bugs to tune away.
- **Limitation (state in the methodology chapter):** overlap on synthetic
  suites ≠ overlap on ParEval LLM code (dense, isolated bugs vs. diffuse or
  none).
