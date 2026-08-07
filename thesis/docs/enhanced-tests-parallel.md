# Enhanced tests on omp/mpi — serial gates, documented residual risks

Since 2026-08-06 the enhanced-tests stage
([`thesis/evaluation/run_enhanced_tests.py`](../evaluation/run_enhanced_tests.py))
can run omp and mpi samples: `stages.enhanced_tests.execution_models`
selects the coverage (default `[serial]` = the historical behavior; the
pilot sets all three). Parallel samples build with their own BuildConfig
(`-fopenmp` / `mpicxx`) and launch at **one fixed point**
(`enhanced_launch: {omp_threads, mpi_ranks}`) through the correctness
stage's `LaunchConfig` — deliberately no launch grid; that axis belongs to
the correctness stage. Records carry `execution_model` as an explicit
field, and the overview summarizes verdicts per execution model
("Enhanced tests by execution model").

## The deliberate simplification: gates stay serial

The per-spec gates — the baseline selftest (crash/hang probe) and the
fast-math stability probe — run the **serial oracle TU**, and their
verdict (`baseline_incompatible` / `numerically_unstable`) is applied to
samples of **all** execution models. `spec_key` and the gate caches are
unchanged; `baseline_selftest.py` is untouched.

This is a **pilot decision**: the risks below are documented and handled
by manual sighting, not solved in code. Solving them would require
per-execution-model gates (an omp/mpi forwarding wrapper plus launch
machinery inside the gate), which triples gate cost and adds a second
source of gate divergence before the pilot has shown whether the problem
is real at scale.

## Residual risk (a): driver divergence

A spec that passes the serial gate exercises the serial driver path. The
omp/mpi drivers run **different code** around the same kernel (`BCAST` of
the input, `IS_ROOT`-guarded validation, per-rank setup). A spec can
therefore be gate-clean serially and still crash or hang in the omp/mpi
*driver* path — independent of the model's kernel.

**Consequence for the pilot:** omp/mpi `crash`/`timeout` cells must be
sighted **manually** before being interpreted as model errors. The
overview section says so next to the numbers. Cases where the same spec
crashes across *all* models of one execution model are the driver-divergence
signature (the model kernel varies, the driver does not).

## Residual risk (b): parallel rounding against a serial oracle

The oracle is serial; parallel model code reduces in a different order.
The fast-math stability probe catches part of this **serially** — it
perturbs the oracle with reassociation/FMA freedom, which is exactly the
freedom OpenMP reductions exploit — but it cannot represent every
parallel reduction order (nor MPI's staged reductions).

**Expectation for reading `fail` cells:** small relative deviations at
many indices are a **rounding signature**, not a model error; a genuine
model bug typically shows large deviations or a structured subset of
indices. The bounded mismatch report (`expected`/`got` per index, parsed
unchanged from omp/mpi output by `parse_mismatch_output`) is the basis of
this rounding-vs-bug classification in the pilot.

## Compile grouping and worker pool (2026-08-08)

The runner compiles ONE binary per (sample, size) group
(`-DENHANCED_RUNTIME_FILL`; the fill pattern travels as environment
variables into a **fresh process per spec** — process isolation
unchanged, see the runtime-fill contract in
[`drivers/cpp/enhanced-fill.hpp`](../../drivers/cpp/enhanced-fill.hpp)),
and runs a worker pool over samples per execution model
(`stages.enhanced_tests.jobs`, CLI `--jobs`). Gates are precomputed
serially before the pool and are **unchanged** (compile-define path,
same defines, same caches). Bit-equivalence of the runtime-fill path to
the old per-spec compiles was verified against the frozen smoke_002
reference (see the equivalence probe in the session report). Timing
semantics are versioned — see timing-and-effort.md ("Enhanced-tests
timing semantics"); operational rules for `--jobs` x multi-terminal
model parallelism: [parallel-execution.md](parallel-execution.md).

## Scope notes

- Held-out principle untouched: enhanced tests run only in phase-2
  backfill, never inside the repair loop, and never feed repair feedback.
- `run_backfill.py`'s gap detection follows the configured
  `execution_models` since 2026-08-07 (it previously hardcoded serial:
  omp/mpi-only iterations were marked not_applicable and never handed to
  the runner). Applicability now means "the iteration contains at least
  one sample of a configured execution model"; existing serial records
  stay valid on resume, and the runner adds the missing (sample, spec)
  pairs itself.
