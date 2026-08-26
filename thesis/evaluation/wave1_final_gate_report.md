# Wave 1 — Final Gate Report

Comparator, non-finite classification, verdict transport, Validation transport
and their direct repair/reporting consumers.

`WAVE 1 COMPLETE` in this document means exactly that scope. It does **not**
mean `pilot_002 APPROVED`, full-run ready, or that the benchmark/oracle/domain/
prompt/generator/assembly/tool-state gates are closed. Those are separate later
gates and are listed in section 13.

---

## 1. Repository base

```
branch          thesis-static-analysis
commit before   ffc3e226881600c06788ce58fc198a3e65860f7c   (matches the expected base)

git status --porcelain (before):
?? thesis/results/analysis/pilot_001/pilot_readiness_review.md
?? thesis/results/analysis/pilot_001/validation-report.md
```

HEAD matched the expected base commit exactly. The only working-tree deviation
was the two pre-existing untracked analysis reports, which are irrelevant to
this contract and were not touched.

---

## 2. F0 — transport and consumer inventory

### 2.1 Producers

| Producer | File:line | Kind |
|---|---|---|
| `parevalEmitValidation` | `drivers/cpp/harness-markers.hpp:93` | trusted producer (NEW) — the single Validation emitter |
| `mismatchNoteNonFiniteReference` | `drivers/cpp/utilities.hpp:363` | trusted producer — the BI marker |
| serial driver | `drivers/cpp/models/serial-driver.cc:54` | trusted producer, via the helper |
| omp driver | `drivers/cpp/models/omp-driver.cc:57` | trusted producer, via the helper |
| mpi driver | `drivers/cpp/models/mpi-driver.cc:63` | trusted producer, via the helper, **inside the existing root-only verdict path** |
| mpi+omp driver | `drivers/cpp/models/mpi-omp-driver.cc:66` | trusted producer, root-only path |
| kokkos driver | `drivers/cpp/models/kokkos-driver.cc:54` | trusted producer (out of thesis scope, kept consistent) |
| cuda driver | `drivers/cpp/models/cuda-driver.cu:93` | trusted producer (out of thesis scope, kept consistent) |
| hip driver | `drivers/cpp/models/hip-driver.cu:93` | trusted producer (out of thesis scope, kept consistent) |

Before this wave all seven drivers carried their own
`printf("Validation: %s\n", ...)`. There is now exactly one emitter.

### 2.2 Parsers and consumers

**Thesis runtime (authenticated, production):**

| Site | File:line | Role |
|---|---|---|
| `parse_authenticated_validation` | `thesis/evaluation/run_correctness.py:231` | the ONE production Validation parser |
| `classify_baseline_incompatible` | `thesis/evaluation/run_correctness.py:333` | the ONE production BI parser |
| `run_verdict` | `thesis/evaluation/run_correctness.py:453` | verdict mapping |
| `run_sample` | `thesis/evaluation/run_correctness.py:590,603,613,639` | correctness stage: token per grid point |
| `run_binary` | `thesis/evaluation/run_enhanced_tests.py:460,512,524` | enhanced stage: token per spec process |
| `sanitized_child_env` | `thesis/evaluation/run_enhanced_tests.py:428` | places the caller's token in the child env |
| `compile_and_run` | `thesis/enhanced_tests/baseline_selftest.py:317,345,357` | baseline gate: token per probe process |
| `build_and_run` | `thesis/experiments/opt_level_probe.py:171,188,189` | experiment: token per run |

**Thesis legacy / read-only (explicitly named, never verdict-relevant for new runs):**

| Site | File:line | Role |
|---|---|---|
| `legacy_parse_validation` | `thesis/evaluation/run_correctness.py:211` | exact historical line only, for upstream/read-only analysis |
| `legacy_count_baseline_incompatible` | `thesis/evaluation/run_correctness.py:381` | unauthenticated BI count, read-only analysis |
| `count_baseline_incompatible` | `thesis/evaluation/run_correctness.py:~310` | raw count; never decides a verdict on its own |

**Upstream / legacy (deliberately NOT converted):**

| Site | File:line | Role |
|---|---|---|
| `RunOutput._parse_output` | `drivers/driver_wrapper.py:68` | upstream parser used by `drivers/run-all.py` |
| `drivers/run-all.py` | — | never sets `PAREVAL_BI_NONCE`, so its driver stays in legacy mode |
| `test/validate-test-results.py` | — | reads run-all's JSON, not stdout; second-order consumer |
| `test/test-serial.bash` | — | drives run-all.py; legacy mode |
| `drivers/cpp/cpp_driver_wrapper.py` | — | builds/links only; parses no verdict |

**Direct string tests found (F0.1):** the only `split(":")`-style Validation
parse in the repository was `drivers/driver_wrapper.py:69`

```python
validation = line.split(":")[1].strip() == "PASS"
```

This is exactly the construct the contract warned about: it compares the WHOLE
remainder, so `Validation: PASS nonce=<hex>` would have been read as **FAIL**.
It is the reason the driver keeps a byte-identical legacy mode (F1.3), and the
field extraction was additionally made robust (see section 5).

### 2.3 `thesis/docs/` versioning state (read-only, F0.4)

```
git check-ignore -v thesis/docs/                       -> exit 1 (the path itself is not reported)
git check-ignore -v thesis/docs/benchmark-domain-table.json
   -> .gitignore:25:thesis/docs/   thesis/docs/benchmark-domain-table.json
```

`git ls-files thesis/docs/` — **9 TRACKED** files:

```
benchmark-example-consistency.md   enhanced-tests-parallel.md   environment-notes.md
model-set.md                       parallel-execution.md        pilot-001-corrected-numbers.md
repair-loop-design.md              static-analysis-filtering.md timing-and-effort.md
```

Present locally but **IGNORED and untracked** (4):

```
benchmark-domain-table.json        1,130,195 B   <- the domain table
fft-family-consistency.md            110,877 B
oracle-audit-calibration-45.md        47,589 B
oracle-correctness-audit.md          207,255 B
```

The rule `thesis/docs/` was added to `.gitignore` after those 9 files were
already tracked; git keeps tracking them, but every NEW document under
`thesis/docs/` — including the domain table and the three audit documents — is
invisible to version control. **`.gitignore` was not changed and nothing was
versioned in this wave**; the state is reported only. This is an open gate
outside Wave 1 (section 13).

### 2.4 CI triggers (F0.5)

`.github/workflows/serial-tests.yml`:

```yaml
on:
  push:
    branches: [develop]
  pull_request:
    branches: [develop]
```

| Event | Does the comparator gate job run? |
|---|---|
| push to `thesis-static-analysis` | **no** |
| pull request from `thesis-static-analysis` → `develop` | **yes** (`pull_request.branches` filters the BASE branch) |
| push to `develop` | **yes** |

"CI exists" is not "CI ran for this commit": no CI run exists for the current
working tree, because the work happens on `thesis-static-analysis` and no PR to
`develop` has been opened.

---

## 3. F1 — authenticated `Validation: PASS/FAIL`

### 3.1 Formats

```
THESIS-AUTHENTICATED (PAREVAL_BI_NONCE set and non-empty)
    Validation: PASS nonce=<128-bit hex>
    Validation: FAIL nonce=<128-bit hex>

LEGACY (no token in the environment)   — byte-identical to the historical line
    Validation: PASS
    Validation: FAIL
```

One complete line, then an immediate `fflush(stdout)`.

**Threat model (F1.1).** (A) UNINTENTIONAL candidate output is defeated: a
candidate cannot guess 128 random bits. (B) DELIBERATELY adversarial candidate
code that reads its own environment and copies the token is **not** solved and
no cryptographic guarantee is claimed — with one process and one shared stdout
it is not solvable at this level.

**Shared token (F1.2).** BI and Validation use the SAME per-execution token.
The historical environment name `PAREVAL_BI_NONCE` was kept; no second variable
was introduced merely because the old name says "BI". This is documented at the
definition site (`drivers/cpp/harness-markers.hpp:70`).

### 3.2 Where the helper lives, and why not in `utilities.hpp`

The contract's preferred location was `utilities.hpp`. That is **not
implementable**, and the reason was verified rather than assumed:
`drivers/cpp/Makefile` compiles every model driver standalone,

```
%serial-driver.o: %serial-driver.cc
	$(CXX) $(CXX_FLAGS) -o $@ -c $<
```

i.e. **without `-DUSE_<MODEL>` and without `-DDRIVER_PROBLEM_SIZE`**. Including
`utilities.hpp` there fires its two `#error` guards — measured in-container:

```
utilities.hpp:17:2: error: #error "No parallel model not defined"
utilities.hpp:24:2: error: #error "DRIVER_PROBLEM_SIZE not defined"
```

Putting the helper in `utilities.hpp` would therefore break the upstream build
and with it `test/test-serial.bash` and the existing CI job. The helper lives in
a new dependency-free header `drivers/cpp/harness-markers.hpp` (only `<cstdio>`,
`<cstdlib>`), which `utilities.hpp` also includes — so both sides share exactly
ONE token implementation. `mismatchMarkerNonce()` is now a one-line forward to
`parevalHarnessNonce()`.

### 3.3 MPI asymmetry — root-only Validation, rank-local BI

Deliberate and unchanged in control flow:

* **BI** is a LOCAL ORACLE DISCOVERY. Any rank may make it, so any rank emits
  its own marker, at most once per rank, without a root-only filter and without
  a collective.
* **Validation** is the FINAL DRIVER VERDICT. The mpi drivers call the emitter
  from their existing root-only verdict path, so it appears exactly once per
  `mpirun` execution. The helper implements no rank logic.

**F1.5 — proven BEFORE the strict parser rule was armed.** Real runs of a real
benchmark (`fft/05_fft_inverse_fft`) built against the real mpi driver:

```
mpirun -np 2, token set   -> Validation: PASS nonce=aa11bb22cc33dd44ee55ff6600778899     (1 line)
mpirun -np 4, token set   -> Validation: PASS nonce=aa11bb22cc33dd44ee55ff6600778899     (1 line)
mpirun -np 2, no token    -> Validation: PASS                                            (1 line, legacy)
```

Exactly one authentic Validation marker per launch, from the root verdict path.
Only after this was the ">1 authentic marker = transport anomaly" rule enabled.

### 3.4 Parser semantics (F1.6)

| Situation | Result |
|---|---|
| exactly one authentic marker | its verdict (PASS→True, FAIL→False) |
| no authentic marker, no trusted legacy line | `None` → existing missing-marker/process semantics |
| **more than one** authentic marker | transport ANOMALY, `None`, reported. Never "first line wins" |
| unauthenticated line(s) **alongside** an authentic one | the authentic one decides; the others are WARNed. **Not** a harness error |
| authentic BI marker | outranks PASS, FAIL, missing marker, timeout, crash, abort and non-zero exit |
| verdict parsing | complete explicit marker format; never a `"PASS"` substring |
| **no authentic marker BUT an exact trusted legacy line** | `HarnessTransportError` — the token did not reach the child |

Measured behaviour of all of these is in section 12 (F1.8 items 1–16 all green).

The last row deserves a stated caveat: the same signal fires if a candidate
printed exactly the legacy line while the driver died before validating. Both
are conditions under which no model verdict may be derived, so failing loudly is
correct for both; the exception message names both possibilities.

### 3.5 Legacy separation (F1.7)

The non-authenticated parse is now explicitly named `legacy_parse_validation`
and accepts ONLY the exact historical line — an authenticated line is not a
legacy line and returns `None` there. There is no silent fallback in the
production parser. `thesis/evaluation/test_evaluation.py` keeps its original
assertions verbatim against the renamed function, plus one new one.

---

## 4. F2 — token lifetime per child execution

`MARKER_NONCE`, the module-level production token of Wave 1b, **is gone**. Every
launcher mints a fresh 128-bit token immediately before its child:

| Launcher | Site | One token per |
|---|---|---|
| correctness | `run_correctness.py:590` | grid point (serial run / omp launch / one `mpirun` invocation) |
| enhanced | `run_enhanced_tests.py:460` | spec process |
| baseline gate | `baseline_selftest.py:317` | probe process |
| opt-level probe | `opt_level_probe.py:171` | binary run |

`marker_nonce=` parameters exist ONLY so tests can pin a deterministic value;
no production path passes one.

**Honest framing (F2 preamble).** 128 random bits are already not guessable
by accident even when reused inside one runner, so this is **not** a large new
security property. The benefit is transport hygiene: one launch is bound to
exactly one parser, nothing is reused across runs, and the transport fails
closed.

**Fail-loud rules.**

* F2.3 — a production parser called without an expected token raises
  `ValueError` (`run_correctness.py:257` and `:357`). Not `assert` — that would
  vanish under `python -O`.
* F2.4 — a runner that HAS a token whose CHILD did not receive it is detected
  through F1.6 rule 7 and raises `HarnessTransportError`.
* F2.5 — `nonce=None` is only accepted by the explicitly named
  `legacy_parse_validation` / `legacy_count_baseline_incompatible`.

**Measured (F2.6), with the production launcher and a stub that echoes the token
the child actually received:**

| Check | Result |
|---|---|
| two serial child launches | different tokens |
| two omp child launches | different tokens |
| one `mpirun -n 2` | 2 ranks, **one** token, identical on both |
| next `mpirun` launch | different token |
| one `mpirun` launch | exactly one authentic Validation marker |
| enhanced spec launcher | mints per process |
| baseline gate | mints per probe process |
| production parser without token | raises |
| runner has token, child does not | `HarnessTransportError` |

---

## 5. F3 — runtime consumers unified

Every thesis production path now uses the authenticated parsers. Changes made:

* `run_enhanced_tests.run_binary` decided on the raw substrings
  `"Validation: FAIL"` / `"Validation: PASS"`; it now calls
  `parse_authenticated_validation` with the launch token.
* `baseline_selftest.compile_and_run` decided on `"Validation: PASS" in stdout`;
  same change.
* `opt_level_probe.build_and_run` used the unauthenticated `parse_validation`;
  same change.

**Remaining unauthenticated production parsers in the thesis pipeline: 0.**
A repository-wide sweep for `"Validation: PASS"|"Validation: FAIL"|startswith("Validation:")`
leaves only comments, tests, and the explicitly classified legacy paths.

**Legacy paths kept by intent (F3.3).** `drivers/driver_wrapper.py`,
`drivers/run-all.py`, `test/validate-test-results.py` and `test/test-serial.bash`
stay in the nonce-free legacy mode; they were NOT converted to the thesis auth
parser. One robustness-only change was made to `driver_wrapper.py:69`:

```python
validation = line.split(":", 1)[1].split()[0] == "PASS"
```

The verdict is now the first whitespace-separated token after the colon. This is
**not** authentication — it only stops the upstream parser from inverting a run
that inherited a token from the ambient environment and therefore printed
`Validation: PASS nonce=<hex>`. Regression: the real serial driver's real output
is parsed correctly by the real `RunOutput` in both modes (section 12).

**Stale comments corrected (F3.4).** `run_correctness.py` described BI as
"emitted exactly once per process and only by the root rank". That has been
false since Wave 1b. The corrected block states the actual asymmetry: BI at most
once per rank without a root filter; Validation exactly once per `mpirun` from
the root verdict path. The module docstring was rewritten to describe the
authenticated transport.

---

## 6. F3b — dedicated terminal repair status

**Before:** an oracle-side stop was stored as `stopped_clean` with a stop_reason
naming `baseline_incompatible`. Functionally distinguishable, but a consumer
that counts `status == "stopped_clean"` reads a non-evaluable sample as clean.

**Now:** `STATUS_BASELINE_INCOMPATIBLE = "stopped_baseline_incompatible"`
(`thesis/repair/orchestrator.py:99`), added to `TERMINAL_STATUSES`. It is the
only new status value; the correctness `verdict` value set is unchanged and no
record field was added.

**Semantics (F3b.1/F3b.4).** Terminal; not a model pass; not a model failure; no
repair requested; excluded from pass/fail rates; separately reportable. It
applies to every test-consuming variant, i.e. `test_feedback` and
`combined_feedback`. `static_feedback` does not consume correctness verdicts at
all and is unchanged.

**No invented priority order (F3b.2).** This contract defines no general ranking
of terminal states. `repair_unusable` is set by `mark_unusable()` earlier in the
loop, before any correctness record exists, so it cannot collide with the BI
decision inside `evaluate_stop`. A `build_failed` correctness verdict produces
an issue and therefore goes to `active`/`stopped_budget`, never to the BI
branch. Only the reachable BI path was mapped; nothing else was reordered.

**Every explicit status enumeration found and updated (F3b.3):**

| Site | File:line | Action |
|---|---|---|
| status constants | `orchestrator.py:92-99` | new value added |
| `TERMINAL_STATUSES` | `orchestrator.py:101` | new value added → resume treats it as terminal (`orchestrator.py:1144`) |
| `RepairLoop.status_row` | `orchestrator.py:~1860` | new counter key |
| `print_status` table | `run_repair.py:120,140` | new `bi` column |
| `stop_reason_table` | `build_overview.py` | generic Counter; new value appears automatically, plus an explanatory note |
| `clean_but_incorrect` | `build_overview.py` | now filters via `_display_status`, so neither the new status nor a legacy BI row enters the "clean" population |
| resume/done detection | `run_backfill.py:461` | uses `== STATUS_ACTIVE`; a terminal value is automatically "not active" |
| tests | `test_orchestrator.py`, `test_backfill.py`, `test_overview.py`, `test_comparator_semantics.py` | pass unchanged; new assertions added in the comparator suite |

**Historical records (F3b.5).** `pilot_001` is NOT migrated. Measured: its 1903
repair-state records contain `active` 715, `stopped_clean` 632,
`stopped_tests_pass` 337, `stopped_budget` 219 — and **0 records whose
stop_reason mentions `baseline_incompatible`**, because pilot_001 predates the
BI verdict entirely. The read-only legacy separation
(`_display_status` → `stopped_clean (legacy, oracle-side)`) is therefore a
forward-looking safeguard for runs made during the Wave-1b window, not a fix for
existing data.

---

## 7. F4 — Python 3.8 and CI

### 7.1 Runner state before the change

```
comparator job:  runs-on: ubuntu-latest      python-version: '3.x'
```

`ubuntu-latest` currently resolves to Ubuntu 24.04. Python 3.8 reached
end-of-life in October 2024 and is no longer published for that runner image, so
`python-version: '3.8'` there cannot be provisioned by `setup-python`.

### 7.2 CI change (this job only)

```yaml
comparator-semantics:
  runs-on: ubuntu-22.04          # pinned for THIS job only
  steps:
    - uses: actions/setup-python@v4
      with:
        python-version: '3.8'
    - run: python -VV            # the interpreter actually used is printed
```

No new CI architecture, no trigger change, no change to `serial-tests` or
`all-serial-tests`. `ubuntu-22.04` is an existing GitHub runner image that still
carries Python 3.8.

**Stated limitation:** GitHub Actions cannot be executed from the development
host, so this pin is chosen from documented runner availability and is **not**
verified by an actual CI run. Runner-image lifecycle is an external dependency:
if `ubuntu-22.04` is retired, this job must be revisited. This is why the gate
was ALSO verified locally on a real 3.8 interpreter.

### 7.3 Real Python 3.8 execution (F4.4/F4.5)

Verification environment (scratch, outside the repository):
`python:3.8-slim` + `g++ 12.2.0` + `Open MPI 4.1.4` + `pyyaml/tqdm/anthropic/openai/python-dotenv`.

```
python -VV  ->  Python 3.8.20
```

Imports — all OK: `run_correctness`, `run_enhanced_tests`, `baseline_selftest`,
`build_overview`, `feedback`, `orchestrator`, `opt_level_probe`,
`drivers/driver_wrapper.py`.

Syntax gate: `python -m compileall -q thesis/evaluation thesis/repair
thesis/analysis_overview thesis/enhanced_tests thesis/experiments
thesis/generation thesis/assembly thesis/config thesis/static_analysis drivers`
→ **rc=0**.

Full suite results under 3.8 in section 12.

Side finding, outside this scope: `google-genai` (in `thesis/requirements.txt`)
does not install on Python 3.8. It is only needed by the generation stage, not
by anything in the Wave-1 scope; the 3.8 verification image therefore omits it.

---

## 8. F5 — read-only Wave-1 evidence

### 8.1 Existing Wave-1b report (F5.1)

No Wave-1b STOP report exists as a file anywhere in the working tree (tracked,
untracked or ignored) — it was delivered in conversation only. The audits below
were therefore re-executed rather than cited.

### 8.2 Self-declared Validation output in `pilot_001` (F5.2/F5.3)

Scanned: 7 run ids, 1111 assembled sources, 1111 raw generations, 1111 distinct
`(run, sample)` pairs, 3512 stored grid runs.

| Search | Samples |
|---|---|
| **A strict** — output statement with literal `Validation:` | **0** |
| A superset — any string literal containing `Validation:` | **0** |
| **B strict** — output statement with the BI marker | **0** |
| B superset — any string literal containing `BASELINE_INCOMPATIBLE` | **0** |
| **C broad** — token `validation`, any spelling | **13** |
| stdout anomalies (>1 `Validation:` line, or any BI line) | **0 / 3512** |

Stored stdout **is** available (1082 of 1111 samples; the other 29 are
`build_failed` with no runs) and is **complete** — the longest stored stdout is
389 characters against a 4000-character cap, so nothing was truncated.

**Effectiveness classes:** 0 provably effective, 0 potentially effective,
**13 provably ineffective** — either the complete stored stdout shows exactly one
`Validation:` line (the driver's), or the build failed and the binary never ran.
All 13 hits are prose: comments and leaked chain-of-thought.

Since new thesis runs are authenticated after F1, this residual uncertainty
concerns the historical integrity of `pilot_001` only, not the new transport.

### 8.3 60-benchmark final check (F5.4)

All 60 current `validate()` bodies were parsed and swept for manual comparison
constructs.

* **60 of 60** use a shared role-aware helper.
* 6 hits for `std::abs(...) > tol` remain — every one of them is the tolerance
  **predicate lambda passed into** `reportAndCompareWith` /
  `reportAndCompareSelectedWith` (fft 05/06/07/09, stencil 52/53), i.e. the
  expression the helper evaluates *after* it has decided the non-finite cases.
  Verified line by line.
* No own `fequal`, no `std::equal`, no direct `==`/`!=` on indexed values, no
  `std::any_of`/`isnan` scan, no candidate-writable container comparison without
  a length check.

**No remaining Wave-1 gap.** Integer/bool/index paths were not probed with
artificial NaNs.

### 8.4 Historical BI + terminal process state (F5.5)

`pilot_001` predates the BI marker, so no historical markers were searched for.
The only surviving trace of a non-finite reference is the `expected=` field of a
stored MISMATCH line.

| | Correctness | Enhanced |
|---|---|---|
| records | 1111 | 22220 |
| samples with ≥1 stored MISMATCH line | 162 | — |
| **non-finite `expected=` (reference)** | **0** | **0** |
| non-finite `got=` (candidate) | 4 | 6 |
| timeout / crash / abort / non-zero exit | 14 | 827 |
| **intersection** | **0** | **0** |

**This 0 is a defensible LOWER BOUND, not proof of absence.** Under the
pre-Wave-1 comparator `std::abs(a-b) > eps` was FALSE for a NaN operand, so a
NaN reference produced no MISMATCH line at all and is structurally invisible in
these records. Only ±Inf references would have been visible, and there are none.
For NaN references the exact number is **not determinable** from the frozen
artifacts. Missing evidence is not read as 0.

---

## 9. F5b — vacuous enhanced passes in `pilot_001`

### 9.1 Candidate independence — proven, with its limit (F5b.1)

Read from the real control flow, not assumed:

* In **attempt 1** the inputs are drawn (`ENHANCED_FILL` / `fillRand`, plus any
  direct `rand()` in `validate()`), the reference is computed by `correct*()`,
  and only then is the candidate called. `init()`/`reset()` run before
  `validate()` and are candidate-independent. **Attempt 1's reference is
  therefore bit-identical to the historical one regardless of which
  implementation sat in the candidate slot.**
* In **attempt 2** the inputs are drawn *after* the candidate has run once.
  `fillRand` uses unseeded `rand()`, so a candidate that consumes `rand()` draws
  shifts attempt 2's inputs. Attempt 2 is therefore **not** guaranteed to be
  historically reproducible with a different implementation in the slot.

The audit was run in both configurations and the two are reported separately.

### 9.2 Minimal reference identity (F5b.2)

`(benchmark, size, fill pattern, value_range, k, explicit values)`.

`execution_model` is deliberately not part of the key: the inputs are BCAST from
root and the same oracle runs on every rank. This was **measured, not assumed** —
see 9.6.

### 9.3 Population (F5b.3)

```
enhanced records in the pilot_001 family        22220
historical 'pass' records                       17523
distinct reference identities                     240
   of which carry >= 1 pass record                228
```

A **full census** was run — no sampling, no truncation.

### 9.4 Method (F5b.4/F5b.5)

The REAL model driver, the REAL benchmark `cpu.cc` and the REAL build path were
used (`ret.group_defines`, `ret.compile_sample`, `spec_runtime_env`,
`ret.run_binary`). The baseline was placed in the candidate slot through the
production helper `baseline_selftest.build_wrapper()`. No hand-built oracle
harness — precisely because the inputs depend on unseeded `rand()` and therefore
on the driver's exact call order.

Each identity was run twice: with `MAX_VALIDATION_ATTEMPTS=1` (the exactly
reproducible attempt-1 reference) and with the shipped value 2.

### 9.5 Result (F5b.6)

```
identities audited                                   240   (full census)
attempts=1   pass 205 | baseline_incompatible 29 | crash 6
attempts=2   pass 205 | baseline_incompatible 29 | crash 6
```

The two configurations agree exactly, so the attempt-2 ambiguity did not
materialise for any identity: **0 identities are non-finite only under
attempts=2, and 0 identities are non-reproducible.**

**Retrospectively identified vacuous enhanced passes:**

| | |
|---|---|
| reference identities with a proven non-finite reference | **29 of 240** |
| frozen enhanced `pass` records resting on them | **3610** |
| share of all 17523 enhanced passes | **20.60 %** |
| share of all 22220 enhanced records | **16.25 %** |
| all frozen records on those identities | 4179 |
| distinct `(run, sample)` pairs touched | **447** |
| distinct `(run, sample)` pairs with ≥1 vacuous pass | **407** |

By benchmark:

| Benchmark | vacuous passes |
|---|---|
| `sparse_la/45_sparse_la_sparse_solve` | 2718 |
| `dense_la/00_dense_la_lu_decomp` | 646 |
| `fft/05_fft_inverse_fft` | 149 |
| `scan/30_scan_prefix_sum` | 97 |

By fill pattern: random 1057, extreme_values 843, all_zeros 534, descending 453,
duplicate_at 302, all_same 162, alternating 162, explicit_values 97.

By validation size: 1 → 604, 2 → 836, 3 → 464, 4 → 713, 5 → 80, 6 → 302,
7 → 151, 8 → 231, 14 → 151, 16 → 78.

All 29 affected identities:

| Benchmark | size | pattern | value_range | passes | records |
|---|---|---|---|---|---|
| `00_dense_la_lu_decomp` | 2 | all_zeros | – | 81 | 82 |
| `00_dense_la_lu_decomp` | 3 | all_same | [5.0, 5.0] | 81 | 82 |
| `00_dense_la_lu_decomp` | 3 | alternating | [5.0, 5.0] | 81 | 82 |
| `00_dense_la_lu_decomp` | 4 | all_same | [5.0, 5.0] | 81 | 82 |
| `00_dense_la_lu_decomp` | 4 | alternating | – | 81 | 82 |
| `00_dense_la_lu_decomp` | 4 | extreme_values | – | 81 | 82 |
| `00_dense_la_lu_decomp` | 5 | extreme_values | – | 80 | 82 |
| `00_dense_la_lu_decomp` | 8 | extreme_values | – | 80 | 82 |
| `05_fft_inverse_fft` | 4 | extreme_values | – | 71 | 81 |
| `05_fft_inverse_fft` | 16 | extreme_values | [-1.0, 1.0] | 78 | 81 |
| `30_scan_prefix_sum` | 4 | explicit_values | – | 97 | 103 |
| `45_sparse_la_sparse_solve` | 1 | all_zeros | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 1 | descending | [-10, 10] | 151 | 181 |
| `45_sparse_la_sparse_solve` | 1 | extreme_values | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 1 | random | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 2 | all_zeros | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 2 | descending | [-10, 10] | 151 | 181 |
| `45_sparse_la_sparse_solve` | 2 | descending | [10.0, 30.0] | 151 | 181 |
| `45_sparse_la_sparse_solve` | 2 | extreme_values | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 2 | random | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 3 | all_zeros | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 3 | duplicate_at | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 4 | extreme_values | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 4 | random | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 6 | duplicate_at | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 6 | random | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 7 | random | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 8 | random | – | 151 | 181 |
| `45_sparse_la_sparse_solve` | 14 | random | – | 151 | 181 |

The mechanisms are the expected ones: a zero pivot in unpivoted LU (`00`), an
empty/degenerate COO system at tiny `N` where `N*N*SPARSE_LA_SPARSITY` rounds to
zero non-zeros (`45`), and ±DBL_MAX butterfly overflow (`05`).

### 9.6 Execution-model independence — measured (F5b.2 validation)

A deterministic subset (all 29 non-finite identities plus every 20th finite one,
**40 of 240**) was re-run under **omp** and **mpi** with the real drivers and the
real build path:

```
agree = 40   disagree = 0
```

Every identity classified identically under serial, omp and mpi. Dropping
`execution_model` from the reference key is therefore measured, not assumed.

### 9.7 No rewriting of old numbers (F5b.7)

These records were **not** reclassified in `pilot_001`. The frozen pilot number
stands as recorded. The figure above is a *sensitivity correction under the final
non-finite oracle semantics* — retrospectively identified vacuous enhanced
passes — and belongs beside the frozen number, not in place of it.

---

## 10. F6 — real scratch end-to-end

Two witnesses, both outside `thesis/results`, no model call, no repair
generation, nothing written into `pilot_001`.

### Witness A — ENHANCED, fully historical

```
sample            claude_fable_5__fft__05_fft_inverse_fft__serial__sample_0
model/benchmark   claude_fable_5 / fft/05_fft_inverse_fft
execution model   serial     variant baseline     iteration 0
frozen spec       {"size":16,"pattern":"extreme_values","pattern_params":{"value_range":[-1.0,1.0]},"source":"mutation"}
evaluation stage  ENHANCED
historical status pass
scratch dir       /scratch/w1f/f6/f6_tzn3lrul
```

```
BASELINE_INCOMPATIBLE: non_finite_reference nonce=7efadbd69b2ac90fa70404b7ca979d91
Validation: PASS nonce=7efadbd69b2ac90fa70404b7ca979d91
```

| | |
|---|---|
| execution token | `7efadbd6…` (fresh, per launch) |
| BI markers | authentic 1, unauthenticated 0 |
| Validation parse | `True`, no anomalies |
| **new enhanced status** | **`baseline_incompatible`** (historical: `pass`) |
| enhanced denominator | historical `(1, 1)` → Wave-1 `(0, 0)` — the spec leaves the denominator |
| separately visible | `enhanced_gated`, split into `baseline_incompatible` / `numerically_unstable` |

### Witness B — NORMAL CORRECTNESS

Real frozen artifact, real driver, real parser/verdict/repair/overview chain.
**SYNTHETIC part, labelled:** the non-finite reference is produced by the
harness's own fill pattern 6, because `pilot_001` contains no
correctness-stage sample with a demonstrable non-finite reference (§8.4).
Historical correctness verdict of that sample: `pass`.

```
BASELINE_INCOMPATIBLE: non_finite_reference nonce=7a20554d6b4a68767d2d960588b4ec27
Validation: PASS nonce=7a20554d6b4a68767d2d960588b4ec27
```

| Step | Result |
|---|---|
| 1. reference non-finite | BI markers authentic 1, unauthenticated 0 |
| 2. authenticated Validation parse | `True`, no anomalies |
| 3. correctness verdict | **`baseline_incompatible`** |
| 4. repair feedback rendered | `[]` — **no repair request**; compressed history entry `None` |
| 5. repair terminal status | **`stopped_baseline_incompatible`**, reason `own sources clean at iteration 1 (ParEval baseline_incompatible)` |
| 6. counts toward the correctness denominator | `False` |
| gridpoint field | `0 evaluable (1 excluded)` — never `0/0` |
| trajectory | `\| 0 \| 2 \| 100.0% (1/1) \| NA \|` + `1 artifact-iteration(s) excluded from the ParEval denominator` |
| stop-reason table | `\| stopped_baseline_incompatible \| 1 \|`, `\| stopped_tests_pass \| 1 \|` |

---

## 11. Changed files

| File | Change |
|---|---|
| `drivers/cpp/harness-markers.hpp` | **NEW.** The per-execution harness token and the single trusted Validation emitter; dependency-free so the standalone-compiled model drivers can include it. |
| `drivers/cpp/utilities.hpp` | Includes the new header and forwards `mismatchMarkerNonce()` to it, so BI and Validation share one token implementation. |
| `drivers/cpp/models/serial-driver.cc` | Emits its verdict through the shared trusted emitter instead of its own `printf`. |
| `drivers/cpp/models/omp-driver.cc` | Same. |
| `drivers/cpp/models/mpi-driver.cc` | Same, from the unchanged root-only verdict path. |
| `drivers/cpp/models/mpi-omp-driver.cc` | Same, root-only path. |
| `drivers/cpp/models/kokkos-driver.cc` | Same (outside the thesis scope, kept consistent). |
| `drivers/cpp/models/cuda-driver.cu` | Same. |
| `drivers/cpp/models/hip-driver.cu` | Same. |
| `drivers/driver_wrapper.py` | Legacy upstream parser: the verdict is read as the first token after the colon, so an inherited token can no longer invert a PASS. Still non-authenticated by intent. |
| `thesis/evaluation/run_correctness.py` | New `HarnessTransportError`, `parse_authenticated_validation`, `legacy_parse_validation`, `legacy_count_baseline_incompatible`; the module-level production token is gone; a fresh token per grid point; the BI parser now refuses a missing token; corrected transport documentation. |
| `thesis/evaluation/run_enhanced_tests.py` | Fresh token per spec process; the raw `"Validation: …"` substring decision replaced by the authenticated parser. |
| `thesis/enhanced_tests/baseline_selftest.py` | Fresh token per probe process; authenticated PASS decision instead of a substring test. |
| `thesis/experiments/opt_level_probe.py` | Fresh token per run; authenticated Validation parse. |
| `thesis/repair/orchestrator.py` | New terminal status `stopped_baseline_incompatible`, in `TERMINAL_STATUSES` and in the status summary; an oracle-side stop no longer lands in `stopped_clean`/`stopped_tests_pass`. |
| `thesis/repair/run_repair.py` | The live status table gained a `bi` column so the new status is never folded into "clean". |
| `thesis/analysis_overview/build_overview.py` | `_display_status` separates the new status and legacy oracle-side `stopped_clean` rows for read-only display; `clean_but_incorrect` excludes both; the stop-reason table explains them. |
| `thesis/evaluation/test_comparator_semantics.py` | Regressions for authenticated Validation, token lifetime, the loud transport error, the real model drivers, the upstream legacy parser and the new repair status. |
| `thesis/evaluation/test_evaluation.py` | Uses the renamed legacy parser with identical expectations, plus one assertion that an authenticated line is not a legacy line. |
| `thesis/enhanced_tests/test_enhanced.py` | `sanitized_child_env` now takes the launch token; the test passes one and asserts it reaches the child env. |
| `.github/workflows/serial-tests.yml` | The comparator gate job — and only that job — pins `ubuntu-22.04` and Python 3.8, and prints the interpreter it used. |
| `thesis/evaluation/wave1_final_gate_report.md` | **NEW.** This report (untracked by design). |

---

## 12. F7 — regression results

### 12.1 Comparator/verdict suite — `thesis/evaluation/test_comparator_semantics.py`

```
1125 checks, 0 failures

configurations actually executed:
  serial          serial -DNDEBUG
  omp             omp -DNDEBUG
  mpi   (1 rank)  mpi  -DNDEBUG
  mpi2  (2 ranks) mpi2 -DNDEBUG      <- real `mpirun -n 2`, never a parser mock
```

Coverage added or kept in this wave:

| Area | Cases |
|---|---|
| BI | reference non-finite, candidate non-finite, non-root BI, multi-rank BI, BI+timeout, BI+crash/abort, correct token, foreign token, marker without token |
| Validation | authentic PASS, authentic FAIL, bare candidate PASS before trusted FAIL, bare candidate FAIL before trusted PASS, foreign Validation token, missing authentic marker, **two** authentic markers, exactly ONE marker under `mpirun -n 2`, flush before abort, authentic marker **plus** a bare candidate line (stays valid), legacy-only output in an authenticated run → loud transport error |
| Token lifetime | two serial launches differ, two omp launches differ, one `mpirun` = one token on all ranks, next `mpirun` differs, enhanced/gate/probe mint per process, production parser without token raises, runner-has-token-child-does-not raises |
| Real drivers | legacy driver emits exactly `Validation: PASS`; upstream `RunOutput` still reads it; authenticated driver emits the token form; upstream parser robust against it; `mpirun -n 2` emits exactly one authentic marker |
| Repair status | BI + `test_feedback` and BI + `combined_feedback` → `stopped_baseline_incompatible`; genuine pass unchanged; `static_feedback` unchanged; the value is terminal; every explicit status enumeration knows it; legacy display separation |
| Overview | denominators, gridpoint field shapes, enhanced gate split |

### 12.2 Existing suites

Both interpreters, identical results:

| Suite | Result |
|---|---|
| `thesis/evaluation/test_evaluation.py` | 27 tests passed |
| `thesis/enhanced_tests/test_enhanced.py` | 11 groups passed |
| `thesis/repair/test_feedback.py` | 8 tests passed |
| `thesis/repair/test_orchestrator.py` | 12 groups passed |
| `thesis/repair/test_backfill.py` | 7 groups passed |
| `thesis/analysis_overview/test_overview.py` | 7 groups passed |
| `thesis/generation/test_generation.py` | 10 groups passed |
| `thesis/assembly/test_cleaning.py` | 13 tests passed |

No existing regression was deleted, skipped or weakened. Three were **updated**
because the contract changed the required behaviour, and each got stricter:

* `test_comparator_semantics` — the BI repair state must now be
  `stopped_baseline_incompatible`, not just "not `stopped_tests_pass`".
* `test_evaluation` — the legacy parser is called by its new explicit name, with
  the original expectations verbatim plus one new assertion.
* `test_enhanced` — `sanitized_child_env` takes the launch token and the test
  asserts it reaches the child environment.

### 12.3 Upstream legacy compatibility (F7.3)

The **real** upstream path was executed, not simulated: a copy of
`drivers/`, `prompts/` and `test/` outside the repository, with **no**
`PAREVAL_BI_NONCE` in the environment.

```
make (drivers/cpp)   -> serial-driver.o, omp-driver.o, mpi-driver.o, mpi-omp-driver.o
                        all built with plain `g++ -c` / `mpicxx -c`,
                        i.e. WITHOUT -DUSE_<MODEL> and WITHOUT -DDRIVER_PROBLEM_SIZE
drivers/run-all.py   -> 3 writes, 3 source-valid, 2 builds, 2 runs, 1 valid
test/validate-test-results.py
                     -> expects 3/3/2/2/1 ; SCRIPT_RC=0
```

This is also the direct proof that the helper could not have lived in
`utilities.hpp`: the same `make` invocation compiles the drivers without any of
the macros that header requires.

### 12.4 Python 3.8

```
Python 3.8.20 (default, Sep 27 2024, 06:05:23) [GCC 12.2.0]

thesis/evaluation/test_comparator_semantics.py   1125 checks, 0 failures
thesis/evaluation/test_evaluation.py             27 tests passed
thesis/enhanced_tests/test_enhanced.py           11 groups passed
thesis/repair/test_feedback.py                   8 tests passed
thesis/repair/test_orchestrator.py               12 groups passed
thesis/repair/test_backfill.py                   7 groups passed
thesis/analysis_overview/test_overview.py        7 groups passed
thesis/generation/test_generation.py             10 groups passed
thesis/assembly/test_cleaning.py                 13 tests passed

python -m compileall -q  (whole pipeline, excluding thesis/results)  -> rc=0
```

Exact commands:

```bash
docker run --rm -u 0 -v "<repo>:/workspace" -w /workspace pareval-py38 \
    python thesis/evaluation/test_comparator_semantics.py
docker run --rm -u 0 -v "<repo>:/workspace" -w /workspace pareval-py38 \
    python -m compileall -q thesis/evaluation thesis/repair \
        thesis/analysis_overview thesis/enhanced_tests thesis/experiments \
        thesis/generation thesis/assembly thesis/config \
        thesis/static_analysis drivers
```

`pareval-py38` is a scratch image outside the repository:
`python:3.8-slim` + `g++` + Open MPI + `pyyaml/tqdm/anthropic/openai/python-dotenv`.

---

## 13. F8 — classification

### WAVE 1 COMPLETE

Within the Wave-1 scope (comparator, non-finite classification, verdict
transport, Validation transport and their direct repair/reporting consumers):

| Criterion | Status |
|---|---|
| new thesis Validation is authenticated | yes — `Validation: PASS\|FAIL nonce=<token>`; legacy form only without a token |
| BI is authenticated | yes — same per-execution token |
| Validation emitted exactly once under MPI | yes — measured at `-n 2` and `-n 4`, from the unchanged root verdict path |
| BI still emittable rank-locally | yes — no root filter, no collective; measured with a non-root-only marker |
| token minted per child execution | yes — measured for serial, omp, mpi (one token across ranks), enhanced, gate, probe |
| parser without expected token fails loudly | yes — `ValueError`, not `assert` |
| token that never reached the child is detected loudly | yes — `HarnessTransportError`, measured against the real driver |
| no unauthenticated production Validation parsers left | yes — 0; legacy paths explicitly named and separated |
| upstream legacy compatibility preserved | yes — real `make` + `run-all.py` + `validate-test-results.py`, rc=0 |
| no floating-comparator bypass left | yes — 60/60 `validate()` bodies swept; the 6 remaining `std::abs` uses are helper predicates |
| no size-mismatch bypass left | yes — same sweep |
| BI unambiguous in the repair state | yes — `stopped_baseline_incompatible` |
| every explicit repair-status consumer updated | yes — constants, `TERMINAL_STATUSES`, `status_row`, `run_repair` table, overview display, resume |
| Python 3.8 really executed | yes — 3.8.20, full suite green |
| multi-rank MPI test green | yes — real `mpirun -n 2` in the suite |
| real scratch end-to-end works | yes — two witnesses |
| no open architecture question in this scope | yes |

**One deviation from the contract's preferred implementation, with evidence:**
F1.4 preferred the Validation helper inside `utilities.hpp`. That is not
implementable — the upstream `make` compiles the model drivers without the
macros `utilities.hpp` requires (verified by compiler output, and again by the
successful legacy run in §12.3). The helper lives in the new dependency-free
`drivers/cpp/harness-markers.hpp`, which `utilities.hpp` includes, so there is
still exactly one token implementation. No new architecture beyond that one
header.

**One residual property, stated rather than hidden:** F1.6 rule 7 also fires
when a candidate prints exactly the bare legacy line while the trusted driver
dies before validating. Both cases forbid deriving a model verdict, so the loud
failure is correct for both; the exception message names both.

**One external dependency, stated rather than hidden:** the CI pin
`runs-on: ubuntu-22.04` could not be exercised from the development host.
Python 3.8 was verified locally instead. If that runner image is retired, this
job must be revisited.

---

## 14. Open gates before `pilot_002`

`WAVE 1 COMPLETE` is **not** `pilot_002 APPROVED`. Known open gates outside the
Wave-1 scope — none of them a Wave-1 blocker:

1. **Domain table** — `thesis/docs/benchmark-domain-table.json` is a proposal
   awaiting approval; sizes and degenerate cases are not decided.
2. **Versioning of `thesis/docs/`** — `.gitignore:25` hides every new document
   there, including the domain table and three audits (§2.3). Not changed here.
3. **Numerical parameters** — γ and the row-scale bound for `sparse_la/45`,
   the band width k for `sparse_la/49`, and ε_rel for `reduce/26` are proposals.
4. **Known oracle/benchmark defects** — including the ones this wave quantified
   but did not fix: `45` at tiny `N` (empty COO → singular system), `00` with a
   zero pivot, the `fft` family's convention inconsistencies, `59`'s oracle
   calling the candidate's `isPowerOfTwo`, the sentinel collisions in `19`/`28`,
   the out-of-bounds write in `38`'s driver, and the tie ambiguity in `42`.
5. **The `reduce/26` LARGE conflict** — the proposed LARGE overflows
   mathematically equivalent implementations.
6. **Prompt wave** — 32 benchmarks need a domain-restricting prompt sentence.
7. **Generator wave** — 33 benchmarks need a custom input construction; `01`
   has no `ENHANCED_FILL` site at all, so enhanced specs cannot vary its input.
8. **Enhanced-harness gates** — the baseline gate is serial-only by design;
   `numerically_unstable` vs `baseline_incompatible` policy; spec regeneration
   after any generator change.
9. **Static/dynamic tool-state gates** — LLOV remains a hard blocker; the
   PARCOACH 60 s timeout; the gcc-analyzer false-positive class.
10. **Assembly** — leaked chain-of-thought reaching `generated-code.hpp` (three
    frozen samples, all `build_failed`).
11. **Reporting/provenance** — how the retrospectively identified vacuous
    enhanced passes (§9) are presented next to the frozen pilot number.
12. **LLOV re-pilot decision.**
13. **All-60 consistency gate** — six benchmarks are still marked INCONSISTENT
    by the prompt-vs-oracle check.
14. **`pilot_001` historical integrity** — the NaN-reference blind spot in the
    frozen records (§8.4) cannot be closed retroactively.

---

## 15. `git diff --stat`

See the work report accompanying this file.

## 16. `git status --porcelain` after the changes

See the work report accompanying this file. This report is deliberately
untracked (`??`) and was not `git add`ed or committed.

