# Static Analysis & Correctness Tooling

This document is the reference for which tools the pipeline runs, why, and
how their findings are treated. It backs the methodology chapter.

## Blocking vs. logged

Two classes of findings:

- **Blocking** findings gate the repair loop's stop criterion and are the
  only findings fed back to the model as repair feedback. A sample is
  "clean" when it has zero blocking findings and passes all correctness
  runs.
- **Logged** findings are recorded in the JSONL and used in the analysis
  (per-model finding rates, tool redundancy) but never gate anything.

Rationale: "zero findings from any tool" is unreachable — clang-tidy and
cppcheck always emit style/modernization nits — so using it as a stop
criterion would force every sample through the maximum iterations and make
the "iterations to clean" metric meaningless.

## Tier 1 — core, in the pipeline (blocking)

| Layer | Tool | Blocking subset |
|-------|------|-----------------|
| Compiler diagnostics | g++ `-Wall -Wextra -Wpedantic` | compile errors |
| Compiler diagnostics | clang++ (same flags) | compile errors |
| Static analysis | clang-tidy (`bugprone-*`, `concurrency-*`, `clang-analyzer-*`, `mpi-*`, `openmp-*`) | all of the listed checks |
| Static analysis | cppcheck (`--enable=warning,portability`) | `severity=error` |
| Dynamic | AddressSanitizer + LeakSanitizer | any report |
| Dynamic | UBSan | any report |
| Dynamic | ThreadSanitizer via Archer (OpenMP) | any race report |
| MPI | MUST | deadlocks, type mismatches, request leaks |
| MPI | OpenMPI `--mca mpi_param_check 1` | parameter errors |

Implemented so far: the two compiler diagnostic tools, cppcheck, and
clang-tidy (with the curated check set; the Clang Static Analyzer runs via
its `clang-analyzer-*` checks). The rest plug into the same Tool interface
(thesis/evaluation/framework.py).

### clang-tidy specifics

- Check set: `bugprone-*`, `concurrency-*`, `clang-analyzer-*`, `mpi-*`,
  `openmp-*` (blocking) plus `performance-*` and selected `misc-*`
  (logged). Parsed from `--export-fixes` YAML, which reports byte offsets;
  these are converted to line/column against the assembled source.
- The model file is never compiled standalone — the benchmark's `cpu.cc`
  includes `utilities.hpp` (which defines `NO_INLINE` and pulls in the std
  headers) immediately before `generated-code.hpp`. clang-tidy therefore
  force-includes `utilities.hpp` so it analyses the same translation unit
  the compiler sees; without it every sample fails to parse.
- A `clang-diagnostic-error` in the output means clang-tidy could not parse
  the TU; it is forced blocking so an unanalysable sample is never counted
  clean.

## Tier 2 — supplementary, logged

| Tool | Adds | Decision |
|------|------|----------|
| lizard (complexity) | cyclomatic complexity, nesting, NLOC per model | keep — only quantitative quality dimension beyond pass/fail |
| Format-compliance | from cleaning metadata (fences, signature echo, auto_closed) | keep — free, already produced |
| Valgrind/Memcheck | uninitialized reads (ASan cannot find these) | keep as optional full-run pass, off in smoke |
| Infer (Pulse) | third independent memory-safety engine | on probation — measure unique-finding rate in the pilot; drop with documented rationale if redundant |

The pilot explicitly measures, per tool, how many findings are unique
(not reported by any other tool). A tool with ~0 unique findings over the
pilot is dropped, and that redundancy result is itself reported.

## Tier 3 — deliberately skipped

- PVS-Studio — commercial license; hurts reproducibility for examiners.
- CodeQL — per-sample build DB tracing is massive overkill for 30-line
  kernels; little unique signal over clang-tidy + cppcheck + Infer.
- MemorySanitizer — needs a fully instrumented libc++ to avoid false
  positives; Valgrind covers the uninitialized-read gap instead.
- Helgrind/DRD — Archer/TSan is superior for OpenMP.
- ROMP, LLOV — academic, unmaintained, integration risk.
- Intel Inspector/ITAC — commercial / deprecated.

## Compiler selection

The primary compiler (g++ or clang++) is a runner flag
(`--primary-compiler`). The same BuildConfig drives both the diagnostic
compile and (later) the correctness compile, so analysis sees exactly the
flags the compiler saw. MPI always uses `mpicxx` regardless of the primary
compiler, since the wrapper injects the correct MPI include/link flags.

ThreadSanitizer for OpenMP is the one exception that will force clang +
LLVM libomp regardless of the primary compiler: TSan with g++/libgomp
produces known false positives on the runtime internals, which Archer
(clang's OMPT-based race detector) filters. To be verified when the
sanitizer stage is built.

## Known finding: driver noise

The diagnostic compile builds the whole program (model driver + benchmark
`cpu.cc` + the model's `generated-code.hpp`). The upstream driver and
benchmark code themselves produce `-Wextra` warnings (unused parameters,
sign-compare). These are not the model's fault and must not count against
it. Mitigation for the static-analysis stage: cppcheck and clang-tidy are
pointed at the model source only (the `generated-code.hpp` translation
unit), while the compiler-diagnostic tool — which must compile the whole
program — will attribute warnings by source file and only count those
located in `generated-code.hpp`. This file attribution is implemented in
the compiler tool: model-file findings are kept, non-model warnings are
dropped (still visible in raw stderr), and a non-model compile *error* is
kept but tagged "(in driver/benchmark)" since it still means the sample
does not build.
