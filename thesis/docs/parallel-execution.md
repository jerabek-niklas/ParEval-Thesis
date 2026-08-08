# Parallel execution: operational rules

> Before any run session, also check the per-session environment
> prerequisites (TSan sysctl etc.): [environment-notes.md](environment-notes.md).

Rules for running the pipeline faster by hand — several terminals, each on
its own `--model-id` — and how that composes with the enhanced stage's
`--jobs` worker pool. These are **operating rules, not code enforcement**:
the only guard in the code is an INFO line at stage start when
`jobs x threads/ranks` exceeds `os.cpu_count()` (a hint, never an abort).

## The rule

| Stage class | Examples | Models in parallel |
| --- | --- | --- |
| Light | generation, assembly, static analysis, serial correctness, enhanced serial | **2** |
| Heavy | dynamic analysis, ALL omp/mpi runs, especially memcheck/MUST | **1** |

## Why (measurement quality, not just comfort)

- omp/mpi samples occupy resources **by themselves**: an omp run uses
  `enhanced_launch.omp_threads` threads, an mpi run `mpi_ranks` processes.
  Valgrind (memcheck: 20–50x slowdown) and MUST multiply CPU **and**
  memory on top.
- Overcommitting cores does not just slow the wall clock — it can push
  runs over their timeouts, and those enter the **results** as
  `<tool>_timed_out` / enhanced `timeout` rows. A timeout caused by host
  overload is a **parallelization artifact that looks exactly like a
  sample property**. That is a measurement-quality problem, not a comfort
  problem.
- One terminal per `--model-id` is **mandatory**: two processes on the
  same model id would append to the same JSONLs concurrently and corrupt
  the resume state (the enhanced runner serializes appends only *within*
  one process — the main thread is the single writer there).

## Composing with `--jobs`

The enhanced stage parallelizes over **samples** per execution model
(`stages.enhanced_tests.jobs`, CLI `--jobs 2` or
`--jobs serial=2,omp=1,mpi=1`; serial/omp/mpi are **execution models**,
not LLM model ids). Budgets apply to the **product**:

```
effective_load ≈ terminals x jobs x (1 | omp_threads | mpi_ranks)
```

Target: `effective_load <= physical cores`.

### Example budget for 16 cores (guideline values, not law)

| Stage | Terminals x jobs | Approx. load |
| --- | --- | --- |
| Generation / assembly | 2 x 4 | ~8 |
| Static analysis / serial correctness | 2 x 4 | ~8–12 |
| Enhanced serial | 2 x 2 | ~4 |
| Enhanced / dynamic omp | 1 x 1–2 | ~4–8 (x4 threads) |
| Enhanced / dynamic mpi | 1 x 1–2 | ~4–8 (x4 ranks) |
| memcheck / MUST | 1 x 1 | conservative |

### Control instrument

The overview's timeout columns (`<tool>_timed_out`, enhanced `timeout`
counts, the timeout share in "Runtime cost per tool") are the check: if
timeouts **rise under parallel operation**, reduce parallelism and repeat
the affected runs — do not read those timeouts as sample properties.

## Scope

`--jobs` exists in `run_enhanced_tests.py` only. `run_static_analysis.py`
and `run_correctness.py` are deliberately unchanged in this rework;
porting the same worker-pool pattern (precomputed shared caches, workers
return records, single-writer main thread) to them is a documented
follow-up, not an accident of scope.
