# Static-Analysis Finding Filtering

This document specifies exactly which static-analysis findings the pipeline
keeps and which it drops, both across all tools and per tool. It is the
reference for the methodology chapter: any finding that reaches the results is
attributable to the LLM-generated code, and every filter below has a stated
reason.

All behaviour described here lives in
[`thesis/evaluation/tools.py`](../evaluation/tools.py) and
[`thesis/evaluation/framework.py`](../evaluation/framework.py).

---

## Two layers: what is *analyzed* vs. what is *reported*

The tools do **not** analyze the generated code in isolation. They analyze the
full **translation unit (TU)**: the benchmark's `cpu.cc`, which `#include`s, in
order, the standard headers, `utilities.hpp`, `baseline.hpp`, and finally the
assembled `generated-code.hpp` (the LLM output). This is the same TU the
compile stage builds, so the analyzers see real types, macros, OpenMP pragmas
and MPI symbols instead of an unparsable fragment.

Analyzing the whole TU means the raw tool output also contains diagnostics from
the driver, the benchmark harness, the helper headers and third-party system
headers (e.g. OpenMPI). **Reporting** therefore applies a filter so that only
findings located in the model's own file survive. That filter is the subject of
this document.

Two orthogonal concepts must not be confused:

- **Filtering** — whether a finding is recorded at all (this document).
- **Blocking classification** — whether a *recorded* finding gates the repair
  loop. Nothing is dropped by being non-blocking; it is still written to the
  JSONL. Blocking is summarized at the end for completeness.

---

## General filtering (applies to every tool)

### 1. File attribution — the model file only

Only findings whose location is the assembled model file
(`generated-code.hpp`) are kept. Everything else is dropped:

- the model driver (`serial-driver.cc`, `omp-driver.cc`, `mpi-driver.cc`),
- the benchmark harness (`cpu.cc`),
- the helper headers (`utilities.hpp`, `baseline.hpp`),
- all system / third-party headers, including the OpenMPI C and C++ binding
  headers (`mpi.h`, `intracomm.h`, `topology.h`, `exception.h`, …).

**Reason:** only the code inside `generated-code.hpp` was produced by the LLM.
A finding in the fixed scaffold or in a library header is not attributable to
the model and would distort per-model finding rates and the repair loop.

Matching is by file **basename** (`generated-code.hpp`), because the tools
report absolute or include-relative paths depending on how the file was
reached. Implemented by:

- `findings_in_model_file()` — used by the cppcheck tool,
- the `file_name != model_file` guard in `ClangTidyTool._parse_fixes()`,
- the per-file attribution loop in `CompilerDiagnosticTool.run()`.

Dropped findings are **not lost for auditing**: the full, unfiltered tool output
is still stored (capped) in the record's `raw_stdout` / `raw_stderr`.

### 2. Compiler exception — non-model *errors* are kept

The compiler tool is the one exception to strict model-file attribution. A
compile **error** anywhere in the TU (driver or benchmark) means the sample
does not build, which is a property of the sample as a whole. Such non-model
errors are therefore kept but re-tagged with `(in driver/benchmark)` in their
`check_id`. Non-model **warnings** are still dropped. Model-file findings are
kept unchanged.

If the compile failed but no blocking finding was parsed from the diagnostics,
a synthetic blocking `compile-failed` finding is added so downstream logic can
treat "did not build" uniformly.

### 3. Raw-output capping (retention, not a finding filter)

`raw_stdout` and `raw_stderr` are truncated to 8000 characters each in the
JSONL (`ToolResult.to_dict`). This bounds file size only; the parsed `findings`
list is never truncated, and the full raw output is reproducible by re-running
the tool on the persisted source.

---

## Tool-specific filtering

### `compiler` (gcc / clang diagnostics)

| Filter | Effect |
| --- | --- |
| Diagnostic regex | Only lines matching `file:line:col: severity: message [-Wflag]` are parsed. Context lines (`In file included from …`, caret/`~` lines, `note:` continuations without the pattern) are ignored. |
| File attribution | Model-file findings kept as-is; non-model findings kept **only if** `severity == error` (tagged `(in driver/benchmark)`); non-model warnings dropped (General filter §1–2). |
| Severity | `error`, `warning`, `note` recognized. Only a non-zero compiler exit / an `error` is blocking; warnings are recorded, not blocking. |

The compile is run with `-Wall -Wextra -Wpedantic` and
`-DDRIVER_PROBLEM_SIZE=(1<<8)`.

### `cppcheck`

Runs over the full TU (`cpu.cc`) with `-DUSE_*`, `-DDRIVER_PROBLEM_SIZE=(1<<8)`,
`--std=c++17`, the same include dirs as the compile, and (for MPI) the MPI
include dirs from `mpicxx --showme:incdirs`.

| Filter | Effect |
| --- | --- |
| `--enable=warning,portability` | cppcheck emits only `error` (always on), `warning` and `portability` findings. `style`, `performance` and `information` findings are **not produced** — filtered at the source. |
| `--inconclusive` | Inconclusive results are included. |
| File attribution | `findings_in_model_file()` keeps only `generated-code.hpp` findings. This is what drops the cppcheck false positives inside the OpenMPI headers (`noOperatorEq`, `duplInheritedMember`, …) observed on MPI samples. |
| Location | Only the **primary** (first) `<location>` of each `<error>` is used for file/line. |
| Severity mapping | `error`→error, `warning`→warning, `portability`→warning, `performance`→info, `style`→info, `information`→info. Only cppcheck `severity == error` is blocking. |

### `clang-tidy` (includes the Clang Static Analyzer via `clang-analyzer-*`)

Runs over the full TU (`cpu.cc`) with the compile flags, `-fopenmp` for OpenMP,
and the MPI include dirs for MPI. This one tool covers both clang-tidy and the
Clang Static Analyzer.

**Enabled check groups** (start from `-*`, then enable explicitly):
`bugprone-*`, `concurrency-*`, `clang-analyzer-*`,
`clang-analyzer-optin.mpi.MPI-Checker`, `mpi-*`, `openmp-*`, `performance-*`,
`cppcoreguidelines-narrowing-conversions`, `misc-*`.

The path-sensitive Clang SA **MPI-Checker** (`optin.mpi.MPI-Checker`) is opt-in.
On the container's clang-tidy (LLVM 18) the `clang-analyzer-*` glob already runs
opt-in checkers, but it is named explicitly so the MPI static-analysis method is
deliberate and version-robust. It is the path-sensitive MPI method, distinct
from the AST-based `mpi-*` checks (`mpi-buffer-deref`, `mpi-type-mismatch`) and
from PARCOACH's dataflow analysis. Note that enabling `clang-analyzer-*` also
pulls in the other opt-in checkers (e.g. `optin.cplusplus.*`,
`optin.performance.Padding`); the OS X ones cannot fire on this C++ code, and
none produced findings on the smoke set, but this is worth re-checking on the
full run.

**Excluded checks** (systematic false positives — see rationale below):

| Excluded check | Why it is excluded |
| --- | --- |
| `misc-include-cleaner` | Include-what-you-use style noise; irrelevant for short single-function kernels that rely on the scaffold's includes. |
| `misc-use-anonymous-namespace` | Not meaningful for code that is embedded as a header. |
| `misc-definitions-in-headers` | The assembled model code is, by scaffold design, **always** a function definition inside a `.hpp` that `cpu.cc` includes. This check would therefore fire on **100 %** of samples — a pure artifact of the benchmark layout, never a model defect. |
| `bugprone-casting-through-void` | OpenMPI macros (`MPI_COMM_WORLD`, `MPI_DOUBLE`, …) expand to C-style `void*` casts inside `<mpi.h>`. clang-tidy attributes the diagnostic to the model's line even though the cast lives in the MPI header, so it fires on essentially **every** MPI sample (observed: 8 of 11 "blocking" findings on one MPI kernel). |

**Location / attribution filters:**

| Filter | Effect |
| --- | --- |
| `--header-filter=generated-code\.hpp$` | Of the *header* diagnostics, only those in `generated-code.hpp` are exported. Diagnostics in `utilities.hpp` / `baseline.hpp` / system headers are not exported. (Diagnostics in the main file `cpu.cc` are always exported by clang-tidy regardless of this filter.) |
| `_parse_fixes` file guard | Additionally keeps only findings whose file basename is `generated-code.hpp`, which drops the always-exported `cpu.cc` main-file diagnostics. Belt-and-suspenders with `--header-filter`. |
| Severity mapping | `Error`→error, `Warning`→warning, `Remark`→info, `Note`→note. |

**`clang-diagnostic-error` safety net:** if clang-tidy reports a
`clang-diagnostic-error` (the TU failed to parse), it is forced blocking so a
parse failure can never be silently counted as a clean sample. Under the
full-TU setup this should not occur; it guards against regressions.

### `infer` (Meta Infer)

Runs `infer run --headers -- clang++ -c cpu.cc <flags>` over the full TU
(capture with Infer's own bundled clang, then analyze) with the same defines and
include dirs as the compile stage, plus the MPI include dirs for MPI samples.
Parses `report.json`.

`--headers` is **required**: the model code lives in `generated-code.hpp`, an
included header. Without it Infer analyzes only the captured `.cc` (cpu.cc) and
silently skips all header code, so it could never report a finding in the model
file (verified: a null-deref injected into the model function is missed without
`--headers`, reported with `file = generated-code.hpp` with it). The trade-off
is that `--headers` also analyzes libstdc++/system headers, which yields many
diagnostics in `/usr/include/...` — all removed by the file attribution below,
at some analysis-time cost per sample.

| Filter | Effect |
| --- | --- |
| File attribution | `findings_in_model_file()` keeps only `generated-code.hpp` findings; Infer diagnostics in the driver / benchmark / helper / system headers are dropped (typically the large majority: e.g. 1 kept of 37 raw when a bug is present, the rest libstdc++ false positives). |
| Severity mapping | `ERROR`→error, `WARNING`→warning, `INFO`/`ADVICE`/`LIKE`→info. Only Infer `severity == ERROR` is blocking (Infer marks genuine defects — null-deref, resource/memory leak, uninitialized value — as ERROR). |
| `bug_type` | Used verbatim as the `check_id` (e.g. `NULL_DEREFERENCE`, `RESOURCE_LEAK`), so Infer's method is identifiable in cross-tool redundancy analysis. |

Infer contributes an **independent detection method** (interprocedural
separation-logic / bi-abduction), distinct from the AST/dataflow checks of
clang-tidy and cppcheck.

### `parcoach` (PARCOACH 2.4.1 — MPI collective verification, own container)

PARCOACH runs in its **own container**
(`registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1`, LLVM 15), not in the
main toolchain image; invoke the same runner inside it:

```sh
docker run --rm -u 0 -v "$(pwd):/workspace" -w /workspace \
  registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1 \
  python3 thesis/evaluation/run_static_analysis.py \
  --config thesis/config/config.yaml --profile smoke --tools parcoach
```

Re-runs **merge per tool** into the existing `static_analysis.jsonl`, so the
two-container workflow does not destroy results of the other container's tools.

**Applicability:** MPI samples only. For serial/OpenMP samples the tool records
`ran=false` with a "not applicable" error (PARCOACH verifies MPI collectives).

**Input reduction (required for robustness, not a finding filter):** PARCOACH
2.4.1 is built/tested for C/Fortran MPI and crashes or hangs on the full C++
benchmark TU. The tool therefore analyzes a **reduced TU** — `<vector>` +
`utilities.hpp` + `generated-code.hpp`, without the benchmark driver — compiled
with the container's clang-15 using `-fno-exceptions -fno-rtti` (removes the
exception landingpads that segfault its Andersen alias analysis) and
`-DOMPI_SKIP_MPICXX` (drops OpenMPI's C++ bindings it cannot model). The
resulting IR is post-processed by `stub_external_declares()`: every external
declaration except `MPI_*`/`PMPI_*` and `llvm.*` intrinsics receives a trivial
body, because PARCOACH aborts fatally (`std::out_of_range` in its ExtInfo
model) on unmodeled externals — reliably triggered by the C++ allocation/throw
symbols any `std::vector` kernel emits.

*Safety argument:* the model function's own IR is unchanged; stubs contain no
MPI calls, so they cannot add or mask collective-ordering errors. Only alias
precision may degrade. The reduced TU excludes driver code, which is fixed
scaffold and not attributable to the LLM anyway.

| Filter | Effect |
| --- | --- |
| Applicability | serial/omp samples are skipped (`ran=false`, "not applicable"). |
| Warning parsing | Only `PARCOACH: <file>: warning: <Collective> line <N> ...` lines become findings; the `remark: No issues found.` line and LLVM noise are ignored. |
| File attribution | `findings_in_model_file()` keeps only `generated-code.hpp` findings (a conditional collective inside `utilities.hpp` macros would be scaffold, not model code). |
| Severity / blocking | All parsed warnings: `check_id = parcoach-collective-ordering`, severity `warning`, **blocking** (a collective possibly not reached by all ranks is a deadlock-class MPI defect). |
| Crash safety | A non-zero parcoach exit or timeout sets the record's `error` field — a crashed analysis is never counted as a clean sample. |

PARCOACH contributes the **LLVM-dataflow MPI method** (control-flow reachability
of collectives over the IR), independent of the AST-based `mpi-*` checks and
the path-sensitive Clang SA MPI-Checker — together giving MPI static analysis
three distinct detection methods.

### `llov` (LLOV — static OpenMP data-race detection, own container)

LLOV runs in its **own container** (`pareval-llov`, built from
`docker/Dockerfile.llov` on top of the LLOV paper-artifact image
`utpalbora/llvm:llov`: Ubuntu 18.04 with LLOV's plugin and its bundled
clang 7.1.0; the derived image only adds Python 3.8 + PyYAML for the runner):

```sh
docker build -t pareval-llov -f docker/Dockerfile.llov .
docker run --rm -u 0 -v "$(pwd):/workspace" -w /workspace pareval-llov \
  python3.8 thesis/evaluation/run_static_analysis.py \
  --config thesis/config/config.yaml --profile smoke --tools llov
```

**Applicability:** OpenMP samples only (`ran=false` "not applicable" for
serial/MPI).

**Invocation (compile-time pass):** LLOV analyzes during a plugin compile of
the same **reduced TU** as PARCOACH (`<vector>` + `utilities.hpp` +
`generated-code.hpp`, no driver) with the canonical flags from LLOV's own
benchmark configuration (`-Xclang -disable-O0-optnone` plus four
`-mllvm -polly-*` flags and `-g`). These flags are **required**: without them
LLOV either reports a race for everything (`-O0` optnone blocks Polly) or
analyzes nothing (`-O1`/`-O2` pre-transform the region) — verified on
known race / race-free pairs, which the canonical invocation discriminates
correctly, including `std::vector` code.

| Filter | Effect |
| --- | --- |
| Applicability | serial/mpi samples are skipped (`ran=false`, "not applicable"). |
| Verdict parsing | `Data Race detected.` blocks → **blocking** finding (`llov-data-race`, location from the `Source :` line). `Region Not Analyzed` blocks → **info** finding (`llov-region-not-analyzed`) so "could not analyze" is never conflated with "race free". `Region is Data Race Free.` → no finding. |
| File attribution | `findings_in_model_file()` keeps only `generated-code.hpp` findings. |
| Crash safety | Non-zero clang exit or timeout sets the record's `error` field (the compile *is* the analysis). |

*Known caveat:* on kernels with multiplied flattened
indexing (`A[i*N+j]`, parameterized `N`) LLOV's polyhedral model may report
false-positive races or fall back to "not analyzed". This is exactly the
per-tool precision that the DataRaceBench overlap measurement quantifies; the
`llov-region-not-analyzed` info findings additionally make the tool's coverage
per sample explicit.

LLOV contributes the **polyhedral dependence-analysis method** for OpenMP,
independent of the AST-based `openmp-*` clang-tidy checks — two static methods
for the OpenMP error class, plus the dynamic tools (TSan/Archer) later.

---

## Dynamic tools (sanitizer-instrumented executions)

The dynamic stage (`thesis/evaluation/dynamic_tools.py`,
`run_dynamic_analysis.py`, output `dynamic_analysis.jsonl`) follows the same
two-layer philosophy: the **whole benchmark program** is instrumented and
executed over the correctness launch grid, and only reports that reach the
model file are kept.

| Tool | Scope | Instrumentation | Attribution filter |
| --- | --- | --- | --- |
| `asan_ubsan` | serial, omp, mpi | `-fsanitize=address,undefined` (primary compiler), `-O1 -g -fno-omit-frame-pointer` | ASan/LSan report blocks: kept only if a stack frame reaches `generated-code.hpp:<line>`; UBSan lines: kept only if the location itself is in the model file. |
| `tsan` | omp only | `-fsanitize=thread`, always clang++ against LLVM libomp with the archer OMPT tool (`OMP_TOOL_LIBRARIES`) — gcc/libgomp+TSan reports false races inside the OpenMP runtime | TSan report blocks: attribution uses **only the racing-access stacks** (frames above the first `Location is` / `Mutex M` / `Thread T… created` metadata section). Rationale: libomp-runtime-internal races (e.g. atomic read vs. `pthread_mutex_init` inside `libomp.so`) carry allocation/thread-creation stacks that pass through the model's `#pragma omp parallel` — attributing on those would flag every OMP sample. |
| `memcheck` | serial, omp (mpi excluded: per-rank valgrind wrapping adds complexity while ASan already covers MPI memory errors) | none (valgrind dynamic binary instrumentation on a plain `-O1 -g` build) — the compile-independent second method for the memory-error class | Valgrind XML errors: kept only if a stack frame reaches the model file. `Leak_PossiblyLost` is dropped entirely: the libgomp thread pool is alive at exit and its allocation stack runs through the first parallel region (model frame), so it fired on 100 % of OMP samples ("320 bytes possibly lost"). Genuine leaks remain covered by `Leak_DefinitelyLost` and LSan. |

**Helgrind and DRD are implemented but disabled by default** — enabling them
is a config decision (`stages.dynamic_analysis.tools`), not a code change.
The default is justified by the suite-scale validation numbers (full
DataRaceBench run, tool_validation/results): Helgrind reaches recall 0.93
but at an FP RATE of 0.89 — it flags nearly every race-free OpenMP kernel,
with frames pointing into the model file so the attribution filter cannot
remove them (stock futex-based OpenMP runtimes are not understood;
Valgrind's manual requires a runtime built with `--disable-linux-futex`).
DRD measures recall 0.20. When enabled, both carry
`low_precision_warning: true`, so all their findings are marked
`low_confidence`. OpenMP race redundancy in the default set is TSan/Archer
(dynamic) + LLOV (static).

**Per-tool config and low_confidence findings.** Every tool of the static
and dynamic stage is configured under `stages.<stage>.tools` with `enabled`,
`execution_models` (may only NARROW the tool's hard capabilities; the config
can never make a tool run where it technically cannot) and
`low_precision_warning` (tool-wide) or `low_precision_families` (check_id
prefixes — used for clang-tidy, whose `clang-analyzer-optin.mpi` family
measured ~0.5 lax precision and 0.011 strict recall on MBI while the rest of
the invocation is unaffected). Marked findings carry `low_confidence: true`
in the JSONLs (schema static_analysis.v2 / dynamic_analysis.v2, per-tool
`num_low_confidence`, per-record `low_confidence_count`). The repair loop
renders them as verify-first hints; their stop semantics are configured via
`stages.repair.low_confidence_stop_mode` (ignore | grace_once |
always_blocking, default grace_once — semantics documented in config.yaml
and tool_config.py).

Further rules:
- Findings are deduplicated per sample across launch parameters by
  `(check_id, line)` — the same race at 2, 4 and 8 threads is one finding.
- All kept dynamic findings are blocking (they are observed runtime bugs).
- A failed instrumented build or a failed TSan preflight is a tool **error**,
  never a clean sample. The TSan preflight exists because TSan binaries crash
  at startup when the kernel's ASLR entropy is too high
  (`vm.mmap_rnd_bits > 28`; Docker Desktop's WSL2 VM defaults to 32 — fix once
  per VM boot with
  `docker run --privileged --rm ubuntu:24.04 sysctl -w vm.mmap_rnd_bits=28`).
- Symbolization requires `llvm-symbolizer` in the image; without it sanitizer
  frames are unsymbolized (`<null>`) and nothing could ever be attributed to
  the model file.

## Blocking classification (adjacent — not a filter)

Recorded findings are marked *blocking* (they gate the repair loop) as follows.
Non-blocking findings are still recorded; they are quality signals, not gates.

| Tool | Blocking when… | Non-blocking (recorded only) |
| --- | --- | --- |
| `compiler` | `severity == error` (or compile failed) | all warnings |
| `cppcheck` | cppcheck `severity == error` | `warning`, `portability` |
| `infer` | Infer `severity == ERROR` | `WARNING`, `INFO`/`ADVICE` |
| `parcoach` | every parsed collective-ordering warning | — |
| `llov` | `llov-data-race` | `llov-region-not-analyzed` (info) |
| `clang-tidy` | check id starts with `bugprone-`, `concurrency-`, `clang-analyzer-`, `mpi-`, `openmp-`; or `clang-diagnostic-error` | `performance-*`, `misc-*`, `cppcoreguidelines-narrowing-conversions`; **exception:** `openmp-use-default-none` (in a blocking group, but a hygiene recommendation that fires on every correct `#pragma omp parallel` — verified via the clean-kernel check — so recorded non-blocking) |

Note that `bugprone-narrowing-conversions` (e.g. `size_t`→`int` for MPI counts)
is **kept and blocking**: unlike the two excluded checks it fires on the model's
actual code, not on scaffold or library artifacts, and is a legitimate quality
signal.

---

## Design principle

Every exclusion above removes a finding that is *not attributable to the LLM*:
either a diagnostic in fixed scaffold / library code (general file attribution),
or a check that fires purely because of the benchmark layout or the MPI
implementation (the two excluded clang-tidy checks). This follows the thesis
principle that each false positive that reaches the model poisons the repair
loop, so the reported set must contain only genuine, model-attributable
findings. False-positive rate is still measured separately; this filtering does
not suppress genuine findings, only structural artifacts.
