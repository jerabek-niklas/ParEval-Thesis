# Environment prerequisites per session

Environment state that does NOT survive a VM/host reboot and silently
degrades runs when forgotten. Run this checklist **before every run
session** (and after every Docker Desktop / WSL2 restart).

## TSan: ASLR entropy (WSL2)

TSan-instrumented binaries crash at startup (SIGSEGV in the runtime, exit
-11) when the kernel's ASLR entropy is too high. Docker Desktop's WSL2 VM
defaults to `vm.mmap_rnd_bits = 32`; TSan needs <= 28. **The setting does
not survive a VM restart** — Docker Desktop update, Windows reboot, or
`wsl --shutdown` silently resets it to 32.

Fix once per VM boot (either form works):

```bash
docker run --privileged --rm ubuntu:24.04 sysctl -w vm.mmap_rnd_bits=28
```

```bash
wsl -d docker-desktop sysctl -w vm.mmap_rnd_bits=28
```

**Measured incident (smoke_003, 2026-08-07):** after a VM restart the
whole base run executed with `vm.mmap_rnd_bits = 32` — TSan produced
`ran: false` for ALL 11 models' omp samples. The loss was correctly
recorded (n/a in the overview) but only noticed a day later by manually
cross-checking the runtime table. In a pilot/full run (days of runtime,
VM restarts likely) that is an expensive silent loss of a whole tool
dimension.

## The safety net: environment preflight gates (2026-08-08)

The runners now refuse to start when the environment cannot support the
requested work — failing LOUDLY before any record is written instead of
persisting degraded data:

- `run_dynamic_analysis.py` preflights every enabled tool once (TSan: a
  real compile+run probe that catches exactly the ASLR case; others:
  availability). Failure aborts with the cause and the remedy command.
  `--skip-unavailable-tools` knowingly proceeds without the failing
  tools; the drop is warned per tool and persisted as `tools_skipped` in
  `dynamic_analysis_summary.json`.
- `run_static_analysis.py` aborts when ALL requested tools are
  unavailable (wrong host/container); individual unavailable tools stay
  a warning (legitimate under the parcoach/llov container split) and are
  persisted as `tools_skipped` in `static_analysis_summary.json`.
- `run_correctness.py` / `run_enhanced_tests.py` abort when the
  toolchain for the configured execution models is missing (g++, and
  mpicxx + mpirun for mpi) — otherwise a missing compiler would produce
  a full dataset of build_failed records that reads like model failures.

The gates address the ENVIRONMENT case only. A tool failing on one
concrete sample keeps its `ran: false` entry — that is a data point, not
an environment error.

## Related

- Container map: main toolchain = pareval-thesis; parcoach =
  parcoach-demo:2.4.1; llov = pareval-llov (see config
  external_tool_commands).
- Parallel operation budgets and the timeout-column control instrument:
  [parallel-execution.md](parallel-execution.md).
