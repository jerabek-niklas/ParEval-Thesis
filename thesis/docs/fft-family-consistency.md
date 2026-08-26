# FFT Family Consistency Audit

Mathematical audit of `05_fft_inverse_fft`, `06_fft_dft`, `07_fft_fft_conjugate`, `08_fft_split_fft`, `09_fft_fft_out_of_place` (names verified against `drivers/cpp/benchmarks/fft/` — the briefing's list was correct). Date: 2026-08-22. Analysis only; no fix implemented, no decision executed. Everything below is **executed** evidence: five per-benchmark audits (pure-Python O(N²) reference under 12 convention candidates × the compiled baselines over N ∈ {1,2,3,4,5,7,8,16} × 5 input classes, ASan/UBSan domain probes), a cross-family roundtrip harness linking all five real baselines, a 100-spec gate replica, binary-level pilot re-runs, and a token-level provenance analysis — followed by three adversarial verifications (all **CONFIRMED**; their precision notes are quoted inline). Scratch artifacts live in the session scratchpad (`fft_audit/*`), outside the repo.

## Executive Summary

1. **The oracle family is internally consistent and composes to the identity.** 06, 08, 09 implement the same transform — the unnormalized negative-exponent DFT (08 and 09 bit-identical; 06 agrees to 1.4e-13) — and 05 is its exact inverse (positive exponent, the family's only 1/N, placed exactly once): every forward∘inverse pair holds at ≤ 6.6e-15 over N ∈ {4,8,16} × all input classes; normalization probes are exact (error 0.0). There is **no cross-benchmark convention clash at the oracle level.** The family's defects live in the **prompt examples** — plus one genuine oracle bug in 07.
2. **06 (example defect, confirmed):** the worked example `[30, -8-12i, -10, -8+12i]` is the elementwise conjugate of what `correctDft` produces; on real input it is indistinguishable between "positive-exponent DFT", "conjugated DFT⁻" and "unnormalized inverse". The oracle is the standard engineering convention (matches the rest of the family and composes with 05). Class **A** (+ B: the prompt text never states the sign, so the wrong example is the only disambiguator).
3. **07 (three-way inconsistency; one part is a NEW oracle bug, class C):** the prompt text demands "FFT then conjugate"; the perf reference `correctFft` implements exactly that (conj(DFT⁻), bit-identical to conj(09)); but the **grading oracle `fftCooleyTookey` conjugates at every recursion level and is not a Fourier transform at all for N ≥ 8** (N=2 → conj(DFT⁻), N=4 → DFT⁺, N≥8 → matches none of 12 conventions; measured deviation up to 240 at N=16). Today this silently discards 8 of 07's 20 enhanced specs as `baseline_incompatible` (the *correct* function disagreeing with the *broken* oracle) and grades the surviving specs against a non-DFT. The prompt example, in turn, is the **unconjugated** transform — token-for-token the Rosetta kernel output — so it contradicts both the text and the oracle. Classes **A + B + C + D**.
4. **09 (example typo, confirmed):** exactly one cell, `-2.42421` vs the true `-(1+√2) = -2.41421356…`; the example's own k=7 cell carries the correct digits (conjugate symmetry), proving a digit typo. Class **A**.
5. **05 and 08 are consistent — substantively, not accidentally:** their examples uniquely pin sign and normalization (a sign flip would change 4/8 cells at 6-figure precision; forward/inverse or normalization confusion 5/8), with one named blind spot: a real example input cannot expose input-conjugation errors. Both reproduce under execution to rounding precision.
6. **The whole radix-2 family (05, 07, 08, 09 — not 06) is domain-restricted while no prompt says so:** silently wrong at N=3 and N=6 (sanitizer-clean, exit 0), **heap-buffer-overflow writes** at N=5, 7, 31 (`baseline.hpp:30`/`:35`; abort-vs-silent-corruption is allocation-layout-dependent), formal UB (shift-by-32) at N=1. 06 is a direct O(N²) DFT and is correct for **all** N — the domain problem does not apply to it. Class **D**.
7. **The enhanced-spec layer actively exercises the invalid domain:** 26/100 fft specs are non-power-of-two; the gate catches the crashes (20/100 gated; replica agrees 100/100 with the frozen gate report) but is **structurally blind to the 6 specs that run silently wrong** — for 07/08 even the two-implementation gate is blind because both baselines produce *identical* garbage at N=3. Realized consequence in pilot_001: the only two fft/05 samples implementing a mathematically correct general-N IDFT are the only ones marked "fail"; everything that reuses the prompt's forward-declared radix-2 helper reproduces the oracle's garbage bit-for-bit and "passes". The pilot reconciliation is **full**, with one correction to Phase 0: the third frozen fail per sample — (4, extreme_values) — is a *separate* value-domain artifact (±DBL_MAX overflow + NaN-tolerant comparison deciding the verdict by where non-NaN cells land), not the size-domain hole.
8. **Common cause: the single-transformation hypothesis is refuted; the single-source hypothesis is proven.** No one transformation (sign flip, conjugation, re/im swap, fwd/inv confusion) reproduces all three defective examples — the computed intersection over 18 candidates is empty. What is proven, token-for-token by executing the shipped kernels: 05/07/08/09's examples all derive from the **Rosetta Code C++ FFT** (cited verbatim in 05's `baseline.hpp:11`) run on the classic `[1,1,1,1,0,0,0,0]` — including signed zeros — with 07's example being the **unconjugated** run (the required conjugation was never applied to it). 06's wrong example and 09's typo entered in upstream commit `05af9f8` (ParEval PR #10, 2024-01-16), which also introduced all five baselines; 07's unconjugated example predates it. All prompts are byte-identical to upstream (modulo the stripped `#include <omp.h>/<mpi.h>` prefix in omp/mpi entries); every defect is **inherited**, not introduced by the thesis fork.

---


## Benchmark 05 — 05_fft_inverse_fft

### Mathematical audit: fft/05_fft_inverse_fft

Scratch dir with all probes and raw outputs:
`C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/fft_audit/05_inverse_fft/` (probe.cpp, compare.py, out/*.txt, asan_*.txt).

#### 1. Semantics (from code + execution)

**Files read:** `drivers/cpp/benchmarks/fft/05_fft_inverse_fft/baseline.hpp`, `.../cpu.cc`, `drivers/cpp/utilities.hpp`, `drivers/cpp/enhanced-fill.hpp`.

- `fft()` (baseline.hpp:13-53) is the Rosetta-Code radix-2 decimation-in-frequency FFT: `phiT = (cos(pi/N), -sin(pi/N))` (line 17, i.e. exponent sign **-1**), unnormalized, followed by a 32-bit bit-reversal permutation (lines 36-52) so input AND output are in natural order. In-place.
- `correctIfft()` (baseline.hpp:61-73): conjugate -> `fft(x)` -> conjugate -> divide by `x.size()` (line 72). Net effect: **inverse DFT, exponent sign +1, normalization 1/N on the inverse**, in-place, natural order.
- Driver `cpu.cc`: `validate()` builds random complex input `re,im ~ U[-1,1]` (lines 72-78, `ENHANCED_FILL(real/imag,-1.0,1.0)`), compares generated `ifft` against `correctIfft` with **absolute epsilon 1e-4 per component** (line 93). Default `TEST_SIZE = ENHANCED_TEST_SIZE_DEFAULT(1024)` (line 61); perf path `DRIVER_PROBLEM_SIZE=(1<<8)=256` (`thesis/evaluation/tools.py:44`). `MAX_VALIDATION_ATTEMPTS` defaults to 2 (`utilities.hpp:25-27`).
- Expected symmetry verified: for real input at N=8, `max |out[k] - conj(out[N-k])| = 5.6e-16`.
- Preconditions: mathematically valid only for N = power of two (see section 4). The prompt states no such precondition.

#### 2. Independent reference vs. baseline over N x input classes

Pure-Python O(N^2) DFT/IDFT (stdlib `complex` only; both exponent signs; norms none, 1/N, 1/sqrt(N)) in `compare.py`. Baseline driven by `probe.cpp` including the **real** `baseline.hpp` (read-only mount), compiled and run in Docker:

```
MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" \
  -v "<scratch>:/scratch" -w /scratch pareval-thesis bash -c \
  "g++ -std=c++17 -O2 -I /repo/drivers/cpp/benchmarks/fft/05_fft_inverse_fft probe.cpp -o probe && ./probe N class"
```

Input classes: impulse, constant, real-asymmetric (1..N), complex-asymmetric ((j+1)/2, (3-j)/4), alternating.

| N | result |
|---|--------|
| 1, 2, 4, 8, 16 (all 5 classes each = 25 cases) | **Matches IDFT(sign=+1, norm=1/N)** exclusively; worst max-abs error 3.15e-14 (N=16 realasym). Complex/real-asymmetric inputs uniquely identify sign=+1; symmetric inputs tie both signs, as mathematics requires. |
| 3 (all 5 classes) | **No convention matches** (best-candidate errors 0.333-1.528). E.g. input (1,2,3): baseline gives (1,0), (-1/3,0), (1,0); true IDFT(+1,1/N) is (2,0), (-0.5,-0.288675), (-0.5,+0.288675). |
| 5, 7 (all 5 classes) | Process aborts before printing: SIGABRT exit 134, `malloc(): corrupted top size` (glibc heap check), even at plain -O2 without sanitizers. |

Reference self-check: round trip `|IDFT(+1,1/N)(DFT(-1,none)(x)) - x| = 4.3e-15`. Container python3 has no numpy (second control unavailable; noted).

Raw `fft()` helper on [1,1,1,1,0,0,0,0]: matches DFT(sign=-1, none) to 1.27e-15, output `[4, 1-2.41421i, 0, 1-0.414214i, 0, 1+0.414214i, 0, 1+2.41421i]` - the classic Rosetta example shared by benchmarks 07/08/09.

#### 3. The worked example: CORRECT

Prompt example: input `[1,1,1,1,0,0,0,0]` -> `[{0.5,0},{0.125,0.301777},{0,-0},{0.125,0.0517767},{0,-0},{0.125,-0.0517767},{0,-0},{0.125,-0.301777}]`.

- max |prompt - IDFT(+1,1/N)| = **3.05e-07** (exactly 6-sig-fig rounding: 0.301777 = (1+sqrt2)/8 = 0.30177669..., 0.0517767 = (sqrt2-1)/8).
- max |prompt - IDFT(-1,1/N)| = **0.603554** (the wrong-sign alternative fails).
- Oracle's actual output at print precision is identical to the prompt including the signed zeros `{0,-0}` at indices 2,4,6 (probe prints `0 -0` there).

All 8 cells agree; **no disagreeing cells**. Unlike the Phase-0 claims against 06/07/09, benchmark 05's example is clean. (Structurally, the example equals conj(Rosetta forward FFT example)/8.)

#### 4. N-domain classification (ASan/UBSan, `-O1 -g -fsanitize=address,undefined`)

| N | classification | decisive receipt |
|---|---|---|
| 3 | **wrong output, silent** | exit 0, ASan+UBSan clean; output mismatches every convention by O(1) (section 2) |
| 5 | **heap corruption (OOB write)** | `ERROR: AddressSanitizer: heap-buffer-overflow ... WRITE of size 16 ... 0 bytes after 80-byte region ... SUMMARY: ... baseline.hpp:30 in fft(...)`; plain build: SIGABRT 134 `malloc(): corrupted top size` |
| 7 | **heap corruption (OOB write)** | same, `... 0 bytes after 112-byte region ... baseline.hpp:30`; plain build SIGABRT 134 |

Mechanism: in the butterfly (baseline.hpp:25-30), `b = a + k` indexes past `N-1` when N is not a power of two; line 30 `x[b] = t * T;` is the flagged write. Bonus findings: N=1 -> UBSan `baseline.hpp:45:31: runtime error: shift exponent 32 is too large for 32-bit type 'unsigned int'` (formal UB; output still exactly correct); N=0 and N=2,4 sanitizer-clean.

**Does the prompt restrict to powers of two?** No. None of the three prompt texts (serial/omp/mpi) mention any restriction; the only hint is the N=8 example and the forward-declared radix-2-named `fft` helper. So either the oracle is wrongly restricted relative to the stated task (class D) or the task domain must be explicitly restricted - classification, not decision: **D**.

**Live consequence (pilot receipts).** The enhanced-test layer injects sizes beyond the safe domain: static base sizes `[0,1,2,7]` (`thesis/enhanced_tests/specs.py:134`) plus LLM specs including size 3. The gate caught the crashers (`baseline_selftest.jsonl`: size 7 `"probe1":"crash"` -> `baseline_incompatible`; `spec_gate_report.jsonl`: sizes 5 and 7 excluded) but **passed both size-3 specs** because the baseline runs without crashing there - the gate cannot detect silent mathematical wrongness. In `pilot_001`, size-3 tests ran against all 10 models. Demonstrated reward inversion: `gemini_36_flash__fft__05_fft_inverse_fft__mpi__sample_0` (code in `thesis/results/raw/pilot_001/gemini_36_flash/generations.jsonl`) contains an `n % size != 0` fallback that computes a mathematically correct O(N^2) IDFT (`angle = +2*pi*k*j/n`, result `/n` - exactly the oracle's own convention). MPI runs use `mpirun -np 4` (`thesis/evaluation/build_config.py:202`, `test_evaluation.py:81`), so at N=3 that correct branch executes - and both size-3 specs are scored **fail** (`enhanced_tests.jsonl`). Meanwhile samples that call the provided (broken-at-3) `fft()` helper reproduce the oracle's garbage and "pass". At N=3 the test measures agreement with a broken oracle, not correctness.

#### 5. Provenance

- Prompts: thesis `serial` entry **byte-identical** to upstream `prompts/generation-prompts.json`. `omp`/`mpi` entries differ **only** by dropping the leading `#include <omp.h>\n\n` / `#include <mpi.h>\n\n` (verified: upstream == prefix + thesis, char-by-char). Math content identical.
- `baseline.hpp`: `git log --follow` shows exactly one commit - `05af9f8 "Update Prompts and Add Some Drivers (#10)"` (upstream ParEval import). Never modified.
- `cpu.cc`: additionally touched by `dd7676c "implemented tool verification"`; diff only swaps `TEST_SIZE=1024` -> `ENHANCED_TEST_SIZE_DEFAULT(1024)` and `fillRand` -> `ENHANCED_FILL`. Validation math unchanged.

#### Deviation classes

1. **D** - oracle (and helper fft) valid only for power-of-two N; prompt does not restrict N. N=3 silently wrong, N=5/7 heap corruption (ASan receipts above).
2. **D (active harm)** - enhanced-test pipeline runs two size-3 specs against this restricted oracle; pilot shows a mathematically correct submission scored "fail" at N=3 (reward inversion).
3. **D (minor)** - N=1 formal UB (shift by 32, baseline.hpp:45); output correct in practice; size-1 tests are active.
4. **F** - worked example: correct under the oracle's convention (positive exponent, 1/N inverse); example uniquely disambiguates the otherwise-unstated convention.
5. **F** - prompt byte-diffs vs upstream are include-prefix removal only; no mathematical content changed.

Phase-0 claim for this benchmark ("radix-2 baselines invalid for non-power-of-two N: silently wrong at N=3, heap corruption at N=5/7") is **CONFIRMED with receipts**. The claims about 06/07/09 examples do not apply to 05; 05's example is correct.

#### Commands run (all read-only on the repo)

1. Docker compile+run probe matrix (`g++ -std=c++17 -O2`, N in {1,2,3,4,8,16} then {5,7}, 5 classes + example, exit codes logged).
2. Docker ASan/UBSan build (`-O1 -g -fsanitize=address,undefined`) and runs at N in {1,2,3,4,5,7} and 0.
3. Host `.venv` python: `compare.py` (pure-Python O(N^2) reference, all conventions), prompt byte-compare script, pilot JSONL tallies.
4. `git log --follow --oneline -- drivers/cpp/benchmarks/fft/05_fft_inverse_fft/{baseline.hpp,cpu.cc}`; `git diff 05af9f8 dd7676c -- .../cpu.cc`.

---


## Benchmark 06 — 06_fft_dft

### Audit: fft/06_fft_dft — DFT benchmark

Scratch dir: `C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/fft_audit/06_fft_dft/` (probe.cpp, refcheck.py, probe_out.txt, probe_asan_out.txt, asan_err.txt, example_out.txt).

#### 1. Semantics (from code + execution)

Oracle `correctDft` (`drivers/cpp/benchmarks/fft/06_fft_dft/baseline.hpp:16-29`):

```cpp
double angle = 2 * M_PI * n * k / N;
std::complex<double> c(std::cos(angle), -std::sin(angle)); // Euler's formula
sum += x[n] * c;
```

- Operation: unnormalized forward DFT, `X[k] = Σ_n x[n]·e^{-2πi nk/N}` — **negative exponent**, **no normalization** (no 1/N, no 1/√N anywhere).
- Layout: real input `vector<double>`, complex output `vector<complex<double>>`, natural index order both sides, no bit-reversal, out-of-place; `output.resize(N, 0)` at baseline.hpp:18 makes the oracle self-sizing.
- Algorithm: direct O(N²) double loop — **no radix-2 structure, no power-of-two precondition**.
- Expected symmetry for real input: conjugate symmetry `X[N-k] = conj(X[k])` — observed (e.g. example run: k=1 = −8+12i, k=3 = −8−12i).

Driver `cpu.cc`: `validate()` (cpu.cc:49-87) draws real input uniform in [−1,1] (`ENHANCED_FILL(x, -1.0, 1.0)`, cpu.cc:61; defaults to `fillRand`, enhanced-fill.hpp:461), TEST_SIZE = `ENHANCED_TEST_SIZE_DEFAULT(1024)` (cpu.cc:50; default 1024, enhanced-fill.hpp:78), 2 attempts (`MAX_VALIDATION_ATTEMPTS`, utilities.hpp:26), and compares per component with **absolute** tolerance 1e-4 (cpu.cc:74). Reasonable for double at N=1024.

#### 2. Independent reference — convention identification

Pure-Python O(N²) DFT (stdlib `complex` only, `refcheck.py`), all six candidates {sign ±1} × {none, 1/N, 1/√N}, vs the compiled real baseline over N ∈ {1,2,3,4,5,7,8,16} × {impulse, constant, real-asymmetric, alternating} (complex input class not admissible: signature takes `vector<double>`).

Commands (all recorded):

```
MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" \
  -v "<scratch>:/scratch" -w /scratch pareval-thesis bash -c \
  "g++ -std=c++17 -O2 -I /repo/drivers/cpp/benchmarks/fft/06_fft_dft probe.cpp -o probe && ./probe > probe_out.txt && ./probe example
   && g++ -std=c++17 -O1 -g -fsanitize=address,undefined -I ... probe.cpp -o probe_asan && ./probe_asan ..."
.venv/Scripts/python.exe refcheck.py probe_out.txt
```

Result: **(sign=−1, norm=none) matches all 32 cases to 1e-9 relative — the unique all-case match.** (sign=+1, none) also matches exactly the cases with real spectra — impulse, constant, even-N alternating, N≤2 — the expected degeneracy; every normalized variant fails all N>1 cases.

#### 3. The worked example — Phase 0 claim CONFIRMED

Prompt (baseline.hpp:13-14 and all prompt JSON variants): `[1,4,9,16] -> [30+0i, -8-12i, -10-0i, -8+12i]`.

| k | prompt says | oracle actually produces | reproduced by |
|---|---|---|---|
| 0 | 30+0i | 30 | both signs |
| 1 | **−8−12i** | **−8.0000000000000036 +12i** | prompt: sign=+1; oracle: sign=−1 |
| 2 | −10−0i | −10 −4.1637991171010006e-15 i | both (≈0) |
| 3 | **−8+12i** | **−7.9999999999999911 −12.000000000000004i** | prompt: sign=+1; oracle: sign=−1 |

The prompt's example is reproduced **only** by the positive-exponent unnormalized DFT; the oracle output only by the negative-exponent one. The example equals the conjugate (equivalently index-reversed) oracle output. A model that faithfully implements the example's convention fails `validate()` (random real inputs give non-real spectra; the 1e-4 comparison is per signed component). Class **A** (example wrong w.r.t. the grader), aggravated by **B** (prompt text never states the sign convention; the example is the only disambiguator and points the wrong way). Sign choice alone would be class E — a legitimate convention — but here prompt and grader disagree.

This identical defective example appears in **all seven upstream variants** (serial/omp/mpi/mpi+omp/kokkos/cuda/hip in `prompts/generation-prompts.json`) — an inherited upstream ParEval defect, not thesis-introduced.

Cosmetic (F): example prints exact integers and `−0i`; the actual oracle residues are ~4e-15 / ~3.6e-15.

#### 4. N-domain

- ASan+UBSan build (`-O1 -g -fsanitize=address,undefined`) ran all 32 cases including N=3,5,7: **exit 0, empty sanitizer stderr, stdout byte-identical to the -O2 build** (`diff → IDENTICAL`), and every output matches the independent reference.
- Classification per N ∈ {3,5,7}: **mathematically correct** — no wrong output, no OOB, no heap corruption, no crash, no UB.
- The prompt does not restrict N to powers of two, and it does not need to: the direct O(N²) oracle is valid for all N ≥ 1 (N=0 a no-op by inspection). **The FFT-family radix-2 restriction claim does not apply to 06.** Class F for the N-domain.

#### 5. Provenance

- Prompts: thesis `serial` byte-identical to upstream; thesis `omp`/`mpi` are upstream **minus the leading `#include <omp.h>` / `#include <mpi.h>` prefix**, remainder byte-identical (`upstream.endswith(thesis) == True`). Class F.
- `baseline.hpp`: single commit `05af9f8` "Update Prompts and Add Some Drivers (#10)" (git log --follow) — inherited, untouched by the thesis.
- `cpu.cc`: `05af9f8` + `dd7676c` "implemented tool verification"; diff swaps only `1024 → ENHANCED_TEST_SIZE_DEFAULT(1024)` and `fillRand → ENHANCED_FILL`, both semantics-preserving by default (enhanced-fill.hpp:75-79, 460-462).

#### Verdict

The oracle is a mathematically sound, unnormalized negative-exponent direct DFT valid for **all** N. The single substantive defect is the prompt's worked example, which encodes the opposite (positive) exponent sign at k=1 and k=3 — inherited byte-for-byte from upstream ParEval — misleading any model that trusts the example into producing conjugated output that the validator rejects.

> **Adversarial verification (V1: 06 conventions + roundtrip): CONFIRMED.** Corrections/precision notes: No substantive corrections. Three precision notes for the synthesizer: (a) "Every other convention hypothesis rejected with errors of order 10-85" — on my independent inputs the rejection margins were 2.51 to 75.4 (still >=14 orders of magnitude above the accepted hypothesis); the "10-85" range is specific to the claimant's input set. Additionally, for 06 the label "unique convention (-1,none)" is unique only up to the mathematical identity DFT-(x) == conj(DFT+(x)) on real inputs — my identifier shows conj(DFT+,none) tying at 1.78e-15 because it is the SAME function on real input, not a competing convention; this does not affect the oracle-vs-example mismatch, which is between two genuinely different vectors (conjugates of each other). (b) The exact aggregate error figures (8.7e-15, 7.1e-15, 1.4e-13, 6.6e-15, 4.1e-14, 6.5e-15, "err 1 to 14") are input-set-specific; my independent inputs reproduce the same orders of magnitude (9.65e-15, 1.78e-15, 1.14e-13, <=8.44e-15 at N in {4,8}, <=4.72e-15, <=4.44e-15, err 2 to 9.71) and identical conclusions. (c) The claims section "## roundtrip hard findings" was empty in the input; items 1-5 under "roundtrip key facts" were what I verified.


---


## Benchmark 07 — 07_fft_fft_conjugate

### Mathematical audit: fft/07_fft_fft_conjugate

Scratch dir (all probes, scripts, outputs): `C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/fft_audit/07_fft_conjugate/` (`probe.cpp`, `validate_replica.cpp`, `grading_semantics.cpp`, `reference.py`, `pilot_scan.py`, `out/` with 152 result files).

#### Headline

The benchmark carries **three mutually inconsistent definitions** of the target function, and the one that grades solutions is not a Fourier transform at all:

| Source | Operation | Receipt |
|---|---|---|
| Prompt **text** ("compute the fourier transform... return the imaginary conjugate of each value") | conj(DFT₋(x)), unnormalized | = `correctFft`, matches independent O(N²) reference `exp-/norm=none/conj` exactly at N=1,2,4,8,16 on all 5 input classes |
| Prompt **example** | **un**conjugated DFT₋(x) (≡ conj(DFT₊)) | independent reference: example == `exp-/none/noconj` == `exp+/none/conj` |
| **Validation oracle** (`fftCooleyTookey`, cpu.cc:78) | nested-conjugation recursion — **not a DFT for N≥8** | matches none of 12 conventions (sign × {none,1/N,1/√N} × final-conj) on asymmetric input at N=8,16 |

The two baseline functions in `baseline.hpp` **agree with each other only at N∈{0,2}** (verified by execution at N=1,2,4,8,1024).

#### 1. Semantics (from code + execution)

**`correctFft`** (baseline.hpp:12–55, used only in `best()` for timing, cpu.cc:52): iterative radix-2 DIF butterflies with `phiT = (cos θ, −sin θ)` (line 16, negative exponent), bit-reversal decimation *after* the butterflies (lines 33–49, so natural-order output), then one conjugation pass (lines 51–54). Net: **conj of the unnormalized negative-exponent DFT**, in-place, natural order. Uses `log2(N)` and 32-bit bit reversal → power-of-two only.

**`fftCooleyTookey`** (baseline.hpp:57–85, **the grading oracle** — cpu.cc:78 `fftCooleyTookey(correct)`): recursive DIT, twiddle `std::polar(1.0, -2πk/N)` (line 76), but the conjugation loop (lines 81–84) sits **inside the recursive function body**, so every recursion level conjugates its sub-result. Conjugation is antilinear, so it does not commute out. Measured consequence per size: N≤1 identity (early return at line 59 skips even the top-level conjugation), N=2 conj∘DFT₋, N=4 exactly DFT₊ (two conjugations cancel into a sign flip of the twiddles), N≥8 a transform that is **no DFT under any sign/normalization/conjugation convention** — verified even for *real* asymmetric input (N=8 realasym, k=1: got −12.8853+7.13137i; conj(DFT₋) expects −3.26863−14.4853i; DFT variants all fail).

**`validate()`** (cpu.cc:55–101): TEST_SIZE = `ENHANCED_TEST_SIZE_DEFAULT(1024)` (=1024 stock); complex input, both parts `fillRand(...,-1.0,1.0)` (unseeded `rand()`); oracle = `fftCooleyTookey`; comparison: componentwise absolute `> 1e-3` on real and imag (cpu.cc:88); `MAX_VALIDATION_ATTEMPTS` defaults to 2 (utilities.hpp:25–27). Driver run sizes: `(1<<18)` serial/omp, `(1<<19)` mpi (drivers/problem-sizes.json:65–73) — all powers of two.

#### 2. Independent reference & multi-input check

Pure-Python O(N²) DFT (`reference.py`, stdlib `complex` only), 12 conventions. Probe grid: {correctFft, fftCooleyTookey} × N∈{1,2,3,4,5,7,8,16} × {impulse, constant, realasym, complexasym, alternating}, compiled in the pareval-thesis container (`g++ -std=c++17 -O2`).

- **correctFft**: `exp-/norm=none/conj` at every power-of-two N on every class; the complex-asymmetric class pins the final conjugation uniquely (for real input `exp-/conj` ≡ `exp+/noconj`, as expected mathematically). N=3 matches nothing; N=5,7 crash (below).
- **fftCooleyTookey**: N=1 `noconj` only; N=2 `conj`; N=4 `exp+/none/noconj` **only**; N=8: realasym 4/8 cells off vs best convention, complexasym 4/8; N=16: 12/16 and 16/16 cells off. It agrees with DFT results only on inputs with real spectra (impulse/constant/alternating). Non-power-of-two: nothing matches.

**Decisive experiment** (`validate_replica.cpp`, faithful re-implementation of validate() incl. fillRand-style input): at TEST_SIZE=1024, `correctFft` vs oracle → **1024/1024 mismatching cells (>1e-3), max componentwise diff 83.97**. Also 4/4 at N=4, 4/8 at N=8.

**Grading semantics** (`grading_semantics.cpp`): candidate A = naive recursive `fftConjugate` with the conjugation written at the end of the recursive body (the natural single-function LLM shape) → **0/1024 mismatches, PASSES**. Candidate B = clean recursive FFT helper + one final conjugation (exactly what the prompt text says) → **1024/1024, FAILS**. The benchmark's own `correctFft` as candidate → **FAILS**. The oracle therefore accepts precisely the code that replicates its own nested-conjugation bug.

#### 3. The worked example

Input [1,1,1,1,0,0,0,0], prompt output `[{4,0},{1,-2.41421},{0,0},{1,-0.414214},{0,0},{1,0.414214},{0,0},{1,2.41421}]`.

- Independent reference: prompt output **is** the unconjugated DFT₋ (also = conj(DFT₊)). Numbers are typo-free (2.41421 = 1+√2, 0.414214 = √2−1).
- vs prompt text (conj(DFT₋) = correctFft actual output `[4, 1+2.41421i, 0, 1+0.414214i, 0, 1−0.414214i, 0, 1−2.41421i]`): **4/8 cells disagree** — k=1,3,5,7, imaginary sign flipped.
- vs grading oracle (fftCooleyTookey actual `[4, 2.41421−1i, 0, −0.414214+1i, 0, −0.414214−1i, 0, 2.41421+1i]`): **4/8 cells disagree** — k=1: prompt {1,−2.41421} vs {2.41421,−1}; k=3: {1,−0.414214} vs {−0.414214,1}; k=5: {1,0.414214} vs {−0.414214,−1}; k=7: {1,2.41421} vs {2.41421,1}. This is the precise content of the Phase-0 "re/im transposed at odd indices" claim: **confirmed, as example-vs-oracle**.
- Text+example become mutually consistent only under the positive-exponent reading of "fourier transform" (then the operation is conj∘DFT₊ and the example is right); the oracle matches neither reading.

#### 4. N-domain (ASan/UBSan, `-O1 -g -fsanitize=address,undefined`)

| N | correctFft | fftCooleyTookey |
|---|---|---|
| 3 | clean run, **wrong output** ([1.4,−0.8,2.1] vs true [3.5,−1.3±0.866i]) | identical wrong output, no UB |
| 5 | **heap-buffer-overflow**: `WRITE of size 16 ... baseline.hpp:27 ... 0 bytes after 80-byte region`; at −O2: abort rc=134 `malloc(): corrupted top size` | wrong output (constant: X[0]=4≠5, X[4]=1≠0), no UB |
| 7 | **heap-buffer-overflow**, same site, `0 bytes after 112-byte region`; −O2 abort | wrong output (impulse: X[2],X[5],X[6]=0≠1), no UB |

Extra: N=1 correctFft triggers UBSan `shift exponent 32 is too large for 32-bit type 'unsigned int'` (baseline.hpp:42, `>> (32 − m)` with m=0); N=0 both clean. Overflow site baseline.hpp:27 is `x[b] = t * T;` with b=a+k running past the end for non-power-of-two N.

The prompt nowhere restricts N to powers of two. Stock harness only exercises 2^18/2^19 and TEST_SIZE=1024, so the crashes are latent there. The thesis enhanced-tests stage uses static base sizes {0,1,2,7} (thesis/enhanced_tests/specs.py:134); the repo's own selftest cache (thesis/results/cache/enhanced/baseline_selftest.jsonl) already records for 07: size 1 → `probe1: validate_fail` and size 7 → `probe1: crash`, both `baseline_incompatible` — i.e. the harness has independently observed both the N=1 conjugation drop and the N=7 crash, but its size grid never included N≥4, where the deep oracle disagreement lives (size 2 passes because the two baselines coincide there).

Classification: since the prompt is unrestricted, this is **D — the oracle side is wrongly restricted** (both baseline functions), not a legitimately restricted task; a decision to restrict the task domain would have to be made explicitly (not this audit's call).

#### 5. Upstream comparison and inheritance

- Prompts (thesis/prompts/generation-prompts-thesis.json vs prompts/generation-prompts.json, Python byte comparison): **serial byte-identical**; **omp/mpi differ only** by upstream's leading `#include <omp.h>\n\n` / `#include <mpi.h>\n\n` (`upstream.endswith(thesis) == True`); comment and signature identical.
- `baseline.hpp`: `git log --follow` shows exactly one commit — **05af9f8 "Update Prompts and Add Some Drivers (#10)", Daniel Nichols, 2024-01-16** — an upstream ParEval commit; the nested-conjugation oracle and the pow2-only reference are **inherited upstream defects**, untouched by the thesis.
- `cpu.cc`: upstream rename `fft`→`fftConjugate` (e865425, #15) + thesis ENHANCED hooks (dd7676c); the diff confirms validate() used `fftCooleyTookey` as oracle already upstream.
- Pilot: `thesis/results/intermediate/pilot_001/*/correctness.jsonl` contains **no 07_fft records** (36-record subset per model, no fft benchmarks), so no real-world sample corroboration is available from pilot_001.

#### Deviation classification summary

1. **C** — validation oracle is not a DFT (nested per-level conjugation); rejects textually correct solutions (1024/1024 cells, incl. the benchmark's own `correctFft`), accepts only replicas of its own buggy recursion.
2. **C** — oracle drops conjugation at N=1 (early return before the conj loop); repo selftest independently recorded `validate_fail` at size 1.
3. **A** — worked example shows the unconjugated DFT: contradicts the text under the standard exp− convention (4/8 cells) and contradicts the grading oracle under every convention (4/8 cells, re/im transposed at odd k).
4. **B** — "imaginary conjugate" nonstandard; exponent/normalization convention unspecified; text cannot disambiguate the three competing definitions.
5. **D** — both baselines valid only for power-of-two N (correctFft: heap-buffer-overflow at N=5/7, silent-wrong N=3, UB shift at N=1; fftCooleyTookey: silent-wrong at all non-pow2) while the prompt is unrestricted; latent in the stock harness (pow2 sizes only), surfaced and excluded in the thesis enhanced-tests stage for sizes 1 and 7.

Note (no deviation): the 1e-3 absolute componentwise epsilon against unnormalized 1024-point transforms (magnitudes O(10–100)) is tight but adequate for double precision — class F.

#### Commands (receipts)

All Docker invocations used the validated pattern `MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" -v "<scratch>:/scratch" -w /scratch pareval-thesis bash -c "..."`:
1. `g++ -std=c++17 -O2 -I /repo/drivers/cpp/benchmarks/fft/07_fft_fft_conjugate probe.cpp -o probe` + loop over 8 N × 5 classes × 2 funcs (+`example`); correctFft N=5/7 aborted rc=134 (`malloc(): corrupted top size`).
2. Host: `.venv/Scripts/python.exe reference.py` (convention table above).
3. `g++ ... validate_replica.cpp -o vr && ./vr 1024` (+8, 4).
4. `g++ ... -O1 -g -fsanitize=address,undefined probe.cpp -o probe_asan`; runs at N=3,5,7 (both funcs, realasym) and N=0,1,2 (complexasym).
5. `g++ ... grading_semantics.cpp -o gs && ./gs`.
6. `git log --follow --oneline -- drivers/cpp/benchmarks/fft/07_fft_fft_conjugate/baseline.hpp`; `git log -1 05af9f8`; `git diff 05af9f8 HEAD -- .../cpu.cc`.
7. Python byte-compare of the three prompt entries; scans of `thesis/enhanced_tests/{specs.py,benchmark_shapes.json}`, `thesis/results/cache/enhanced/baseline_selftest.jsonl`, `drivers/problem-sizes.json`, `thesis/results/intermediate/pilot_001/*/correctness.jsonl`.

> **Adversarial verification (V3: 07/09 example verdicts): CONFIRMED.** Corrections/precision notes: Two precision corrections, zero substantive reversals: (1) The claim "4/8 odd cells re/im-transposed (k=1: {1,-2.41421} vs {2.41421,-1})" is loose: the exact relation is example[k] = +/- i*conj(oracle[k]) — a literal re/im transposition only at k=3 and k=7; at k=1 and k=5 (including the claim's own cited k=1 pair) the components swap magnitudes AND both flip sign. All 4 odd cells disagree and all 4 even cells agree, so the substantive count stands. Also the transposition is a per-input numerical coincidence, not the mechanism — example = plain DFT_-, oracle = sign-alternating non-DFT. (2) "max diff 84" at 07's validate config is input-draw-dependent; my independent draw gave max component diff 93.1 with the same 1024/1024 failure count — conclusion unchanged (4-5 orders above the 1e-3 tolerance). ADDITIONAL NUANCE (supports, does not contradict, the A+B dual classification): 07's printed example is not merely "unconjugated by mistake" in an absolute sense — it is a perfectly valid standard unnormalized forward DFT (exp-), and two coherent readings of the prompt text make text and example mutually consistent (exp(+)-convention FT then conjugate; or "imaginary conjugate" as no-op). Example-vs-text wrongness is therefore intent-relative (correctFft evidences the conj(DFT_-) intent, under which the example is wrong at 4 cells); example-vs-oracle and text-vs-oracle inconsistency at N>=8 is reading-INDEPENDENT and absolute.


---


## Benchmark 08 — 08_fft_split_fft

### Mathematical audit — fft/08_fft_split_fft

Scratch dir: `C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/fft_audit/08_split_fft/` (probe.cpp, compare.py, all out_/asan_ logs).

#### 1. Semantics (from code + execution)

**Files.** `drivers/cpp/benchmarks/fft/08_fft_split_fft/baseline.hpp`, `cpu.cc`; helpers in `drivers/cpp/utilities.hpp` + `enhanced-fill.hpp`.

- `correctFft(x const&, r, i)` (baseline.hpp:12-59): copies `x` (line 13), runs an **iterative radix-2 decimation-in-frequency Cooley-Tukey** (`while (k > 1) { ... k >>= 1; ... }`, lines 18-34) with twiddle seed `phiT = (cos(pi/N), -sin(pi/N))` (line 17, **negative exponent**), then an explicit **bit-reversal pass** (lines 36-52, `m = (unsigned)log2(N)` line 36) that restores **natural order**, then splits into `r[j]=Re, i[j]=Im` (lines 55-58). **No normalization anywhere.** `r`/`i` are written by index, never resized — caller must pre-size (the driver does).
- `fftCooleyTookey(x&)` (baseline.hpp:61-84): recursive radix-2 DIT; `std::polar(1.0, -2*M_PI*k/N)` (line 80) — same negative exponent, no normalization, natural order.
- **The validation oracle is `fftCooleyTookey`, not `correctFft`** (cpu.cc:81: `fftCooleyTookey(x_copy);`); `correctFft` is only the timing baseline `best()` (cpu.cc:53). Comparison: `reportAndCompare(correct*, test*, 1e-4)` (cpu.cc:92) = per-element **absolute** `abs(x-y) > 1e-4` (utilities.hpp:315-321, drop-in for upstream `fequal`).
- Input: complex, both parts `U(-1,1)` (cpu.cc:70-77). `TEST_SIZE = ENHANCED_TEST_SIZE_DEFAULT(1024)` (cpu.cc:57), 2 validation tries (`MAX_VALIDATION_ATTEMPTS`, utilities.hpp:25-27). Perf size `1<<17` (drivers/problem-sizes.json:74-82).

#### 2. Independent reference (pure Python O(N^2) DFT, stdlib complex)

Probe (`probe.cpp`) drives both baseline functions; built in Docker:

```
MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" \
  -v "<scratch>:/scratch" -w /scratch pareval-thesis bash -c \
  "g++ -std=c++17 -O2 -I /repo/drivers/cpp/benchmarks/fft/08_fft_split_fft probe.cpp -o probe_o2 && \
   g++ -std=c++17 -O1 -g -fsanitize=address,undefined -I ... probe.cpp -o probe_asan"
```

Grid: {correctFft, fftCooleyTookey} x N in {1,2,3,4,5,7,8,16} x {impulse, constant, real-asymmetric, complex-asymmetric, alternating}, compared (`compare.py`, host venv python, stdlib only) against direct DFT under all 6 conventions (sign +/-1 x norm none, 1/N, 1/sqrt(N)).

**Result:** for N in {1,2,4,8,16}, both functions match **sign=-1, norm=none** with maxerr < 1e-9 (measured ~1e-15) on every input class; asymmetric real and complex inputs at N=4,8,16 select this convention **uniquely** (symmetric inputs also match sign=+1, as they mathematically must). For N in {3,5,7}, **no convention matches anything** (best maxerr 0.55-4.6).

#### 3. The worked example

Prompt: `[1,1,1,1,0,0,0,0] -> r: [4,1,0,1,0,1,0,1]  i: [0,-2.41421,0,-0.414214,0,0.414214,0,2.41421]`.

Independent DFT, sign=-1, norm=none: `X = [4, 1-2.4142135624i, -0, 1-0.4142135624i, 0, 1+0.4142135624i, 0, 1+2.4142135624i]` — the constants are 1+sqrt(2)=2.4142135624 and sqrt(2)-1=0.4142135624. Max deviation from the prompt literals: **3.56e-6 = pure 6-significant-digit rounding**. Every other convention is off grossly (next best 2.59). Both baseline functions reproduce the example to 1.3e-15 and match the prompt literals to the same 3.56e-6.

**Verdict: example correct** (Phase-0's 09 typo claim, -2.42421, does NOT occur in 08; 08 prints 2.41421). Cosmetic only: true DFT yields `-0.0` at i[2]; the prompt prints `0`. Note for cross-family work: 08's example values are numerically identical to 07/09's shared Rosetta example and are the **plain (unconjugated)** DFT.

#### 4. N-domain (ASan/UBSan, `-O1 -g -fsanitize=address,undefined`, plus `-O0` re-check)

| N | correctFft | fftCooleyTookey |
|---|---|---|
| 3 | **wrong output**, memory-safe (rc=0, sanitizers silent) | **wrong output**, memory-safe |
| 5 | **heap corruption**: `AddressSanitizer: heap-buffer-overflow ... WRITE of size 16 ... baseline.hpp:30 in correctFft ... 0 bytes after 80-byte region`, rc=1 | wrong output, memory-safe |
| 7 | **heap corruption**: same report, `0 bytes after 112-byte region`, baseline.hpp:30, rc=1 | wrong output, memory-safe |

Cause at N=5/7: last butterfly level has `k=1, n=2`, inner loop `a=4 (resp. 6) < N`, `b=a+1=N` -> write past end (baseline.hpp:27-30). At `-O2` without sanitizers this was **silent** in our probe (exit 0, garbage values). fftCooleyTookey instead truncates via `N/2` (drops trailing element, leaves stale entries) — wrong but safe.

N=3 receipt (real-asymmetric input `[-5/3, -1/3, 1]`): both functions output `[x0+x1, x0-x1, x2] = [-2, -4/3, 1]`; true DFT = `[-1, -2+1.1547i, -2-1.1547i]`; per-bin |diff| up to 3.21. **Both functions are bit-identical to each other at N=3 on all 5 input classes (max diff 0)** — a differential test is structurally blind there.

Extras: N=1 (in-domain!) triggers UBSan `baseline.hpp:45:31: runtime error: shift exponent 32 is too large for 32-bit type 'unsigned int'` in correctFft (m=0 -> `>> (32-0)`); output still correct on x86. N=0: no runtime finding at -O0/-O1.

**Prompt restriction?** The prompt says only "Compute the fourier transform of x." — **no power-of-two restriction**. So either the oracle is wrongly restricted relative to the stated task, or the task domain must be (but is not) declared power-of-two. Classification (not a decision): **D** for the oracle, **B** for the prompt's silence.

**Pipeline exposure (thesis-specific).** `thesis/config/config.yaml:562` sets `static_base_sizes: [0,1,2,7]`. The pilot's own gate (`thesis/results/cache/enhanced/baseline_selftest.jsonl`) recorded size 7 as `probe1: crash -> baseline_incompatible` and excluded it; a mutation spec at size 5 was likewise excluded (`spec_gate_report.jsonl`). **But three size-3 specs passed the gate** (`spec_gate_report.jsonl`: size 3 all_same/random/all_same, status pass) — at N=3 the crash probe cannot fire and the differential probe cannot disagree, so the enhanced tests actively validate candidates against a mathematically wrong oracle at N=3: a candidate implementing the true 3-point DFT fails with |diff| ~3 against tolerance 1e-4. Class **C** at those sizes.

#### 5. Upstream byte-compare and inheritance

- Prompt entries vs `prompts/generation-prompts.json`: **serial byte-identical**; **omp/mpi differ only by the stripped leading `#include <omp.h>\n\n` / `#include <mpi.h>\n\n`** (verified `upstream == prefix + thesis` exactly, True for both).
- `baseline.hpp`: `git log --follow` shows exactly one commit — `05af9f8` "Update Prompts and Add Some Drivers (#10)", Daniel Nichols, 2024-01-16 — **inherited unchanged from upstream ParEval**.
- `cpu.cc`: two thesis commits on top; `git diff 05af9f8..HEAD` shows only `fequal -> reportAndCompare` (same 1e-4), `fillRand -> ENHANCED_FILL`, `1024 -> ENHANCED_TEST_SIZE_DEFAULT(1024)` — oracle, reference function and tolerance semantics unchanged.

#### Deviation summary

| # | What | Class |
|---|---|---|
| 1 | Oracle valid only for power-of-two N; N=3 silently wrong, N=5/7 heap OOB in correctFft; prompt states unrestricted task | D |
| 2 | Enhanced-tests pipeline accepted N=3 specs where the oracle is wrong and the differential gate is provably blind (bit-identical wrong outputs) | C |
| 3 | In-domain latent UB at N=1 (shift-by-32, baseline.hpp:45); output correct in practice | C (benign) |
| 4 | Prompt omits the power-of-two precondition (sign/normalization ARE pinned by the example) | B |
| 5 | omp/mpi prompt entries differ from upstream only by removed include prefix | F |

**Clean findings:** the worked example is mathematically correct; the convention (sign=-1, unnormalized, natural order, split r/i) is uniquely and consistently implemented by both baseline functions for all power-of-two N tested; thesis driver modifications are semantics-preserving.

---


## Benchmark 09 — 09_fft_fft_out_of_place

### Mathematical audit: fft/09_fft_fft_out_of_place

Scratch dir: `C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/fft_audit/09_out_of_place/` (probe.cpp, check.py, runs/*).

#### 1. Semantics (reconstructed from code + execution)

**Operation.** Unnormalized forward DFT, negative exponent: X[k] = Σₙ x[n]·e^(−2πikn/N). Out-of-place: `void fft(std::vector<std::complex<double>> const& x, std::vector<std::complex<double>> &output)`. Natural (not bit-reversed) index order on input and output.

**Two distinct baseline functions** in `drivers/cpp/benchmarks/fft/09_fft_fft_out_of_place/baseline.hpp`:
- `correctFft` (lines 16–56): copies x into output (`output = x;`, line 17), then iterative radix-2 decimation-in-frequency with negative-sign twiddles (`phiT = complex(cos θ, −sin θ)`, line 22) and an explicit 32-bit bit-reversal permutation using `m = (unsigned)std::log2(N)` (lines 41–55). Used **only** in `best()` (cpu.cc:53) — the performance reference.
- `fftCooleyTookey` (lines 58–81): recursive radix-2 DIT, in-place, `std::polar(1.0, −2πk/N)` (line 77). This is the **actual correctness oracle**: `validate()` runs `correct = x; fftCooleyTookey(correct);` (cpu.cc:78–79) and compares against `fft(x, test)`.

**Comparison** (cpu.cc:87–92): per-element, per-component absolute epsilon:
```cpp
if (std::abs(correct[k].real() - test[k].real()) > 1e-4 || std::abs(correct[k].imag() - test[k].imag()) > 1e-4)
```
`TEST_SIZE = ENHANCED_TEST_SIZE_DEFAULT(1024)` (cpu.cc:57), `MAX_VALIDATION_ATTEMPTS` defaults to 2 (utilities.hpp:25–27). Input: re and im uniform in [−1,1] via `fillRand`/`ENHANCED_FILL` (cpu.cc:68–75) — full complex input. Perf size `DRIVER_PROBLEM_SIZE = (1<<17)` (drivers/problem-sizes.json). **Every size in the stock pipeline is a power of two.**

**Symmetries.** For real input at power-of-two N the output equals the exact DFT to ≤1e-9, hence satisfies conjugate symmetry X[N−k] = conj(X[k]) (verified via realasym class at N=4,8,16).

#### 2. Independent reference: which convention matches

Harness `probe.cpp` (prints IN/OUT at %.17g) built in Docker:
```
MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" -v "<scratch>:/scratch" -w /scratch pareval-thesis \
  bash -c "g++ -std=c++17 -O2 -I /repo/drivers/cpp/benchmarks/fft/09_fft_fft_out_of_place probe.cpp -o probe_o2 && \
           g++ -std=c++17 -O1 -g -fsanitize=address,undefined -I ... probe.cpp -o probe_asan"
```
Sweep: {correctFft, fftCooleyTookey} × N ∈ {0,1,2,3,4,5,6,7,8,16} × {impulse, constant, realasym, complexasym, alternating}, both builds; compared by `check.py` against a pure-Python (stdlib `complex`) O(N²) DFT under 4 conventions (sign ±1 × norm {none, 1/N}).

| N | correctFft | fftCooleyTookey |
|---|---|---|
| 1 | all conventions (identity) | all conventions |
| 2, 4, 8, 16 | **sign=−1, norm=none** (asymmetric classes pin the sign; symmetric classes also match +1, mathematically expected) | same |
| 3, 5, 6, 7 | **NONE** | **NONE** |

Sample receipts (constant input): N=3 → got [2,0,1], true [3,0,0]. N=5 → cooley got [4,0,0,0,1], true [5,0,0,0,0]. N=6 cooley → [4, 0, 0.5−0.866i, 0, 0, 1.5+0.866i], true [6,0,0,0,0,0]. Mechanism: radix-2 recursion on floor(N/2) reads x[0..2⌊N/2⌋−1], silently dropping x[N−1] at odd N (baseline.hpp:66–68), which passes through to the output unchanged.

**Cross-check:** correctFft and fftCooleyTookey outputs are *identical to 1e-12* at N=3 and N=5 (-O2), diverging only at N=7. This defeats any differential test between them at N=3/5 (see §4).

#### 3. The worked example

Input [1,1,1,1,0,0,0,0]; prompt claims `[{4,0}, {1,-2.42421}, {0,0}, {1,-0.414214}, {0,0}, {1,0.414214}, {0,0}, {1,2.41421}]`.

| k | DFT sign=−1 unnorm | DFT sign=+1 unnorm | prompt | verdict |
|---|---|---|---|---|
| 0 | (4, 0) | (4, 0) | {4,0} | ok |
| 1 | (1, **−2.414214**) | (1, +2.414214) | {1,**−2.42421**} | **typo** |
| 2,4,6 | (0, 0) | (0, 0) | {0,0} | ok |
| 3 | (1, −0.414214) | (1, +0.414214) | {1,−0.414214} | ok |
| 5 | (1, +0.414214) | (1, −0.414214) | {1,0.414214} | ok |
| 7 | (1, +2.414214) | (1, −2.414214) | {1,2.41421} | ok |

- sign=−1 reproduces the prompt in 7/8 cells; sign=+1 disagrees in 4 cells → the example encodes **sign=−1, unnormalized** (same as the oracle; no convention conflict in this benchmark).
- Cell k=1: true value 1 − i(1+√2), −(1+√2) = −2.414213562373095. Prompt prints −2.42421 — a digit typo (compare the prompt's own conjugate cell k=7: 2.41421, correct). Error 0.0100 = 100× the driver epsilon; harmless in practice because the example is never machine-checked, but it makes the printed example violate conjugate symmetry of a real-input DFT.
- Oracle actual output (both functions, probe run): `1 −2.4142135623730949i` at k=1 — the *corrected* value, not the printed one.

#### 4. N-domain (ASan/UBSan receipts)

Prompt text: "Compute the fourier transform of x. Store the result in output." — **no restriction on N**.

| N | fftCooleyTookey (validate oracle) | correctFft (best/perf reference) |
|---|---|---|
| 3 | wrong output, sanitizer-clean, exit 0 | wrong output, sanitizer-clean, exit 0 (identical to cooley) |
| 5 | wrong output, sanitizer-clean | **heap corruption**: `AddressSanitizer: heap-buffer-overflow … WRITE of size 16 … baseline.hpp:35 in correctFft` (`output[b] = t * T;`), `0 bytes after 80-byte region`, exit 1. At -O2: exit 0, silent wrong output |
| 7 | wrong output, sanitizer-clean | same ASan report, `0 bytes after 112-byte region`, exit 1; -O2 silent. Thesis selftest independently logged `probe1: "crash"` at size 7 under normal compile (baseline_selftest.jsonl) |

Extra findings: N=1 correctFft triggers `baseline.hpp:49:31: runtime error: shift exponent 32 is too large for 32-bit type 'unsigned int'` (m=log2(1)=0 → `>> (32−0)`); output still correct on x86. N=0: both return empty, no crash. Root cause of the overflow: in the last DIF stage (k=1, n=2) the butterfly index `b = a+k` reaches N for odd N ≥ 5 (baseline.hpp:30–35).

**Classification question.** The prompt does not restrict the task to powers of two; the oracle is only valid there. In the stock upstream pipeline the mismatch is *latent* (validate N=1024, perf N=1<<17). The thesis enhanced-test layer makes it live: its spec generator explicitly requests "edge sizes like 0/1/2/3 and small odd/even sizes" (generate_test_specs.py:231). Its gate (spec_gate_report.jsonl) flagged sizes 5, 6, 7 `baseline_incompatible` but **passed size-3 specs** (all_zeros accepted into specs.jsonl; all_same passed the gate) — because the gate is differential (correctFft forwarded through validate() vs fftCooleyTookey) and the two functions emit *identical wrong* outputs at N=3/5. Consequence: a generated FFT correct for all N would be judged WRONG by validate() at N=3 with any non-zero fill; the accepted zero-fill size-3 spec is merely vacuous (zero discriminative power). This is a D-situation (oracle wrongly restricted relative to the stated task) compounded by a B-situation (the prompt fails to state the precondition); whether to restrict the task domain or generalize the oracle is a decision, not taken here.

#### 5. Upstream identity

- Prompts (thesis/prompts/generation-prompts-thesis.json vs prompts/generation-prompts.json): **serial byte-identical**; omp/mpi identical after removing the upstream-only leading `#include <omp.h>`/`#include <mpi.h>` lines (verified `upstream == header + thesis`, byte-exact). Non-prompt fields identical.
- baseline.hpp: git blob `ef38d612…` identical between working tree and its introducing commit `05af9f8` ("Update Prompts and Add Some Drivers (#10)", Daniel Nichols, 2024-01-16, upstream ParEval) — inherited unmodified; single entry in `git log --follow`.
- cpu.cc: one thesis commit `dd7676c` ("implemented tool verification") replacing `TEST_SIZE = 1024` → `ENHANCED_TEST_SIZE_DEFAULT(1024)` and `fillRand` → `ENHANCED_FILL` only; oracle call, epsilon, loop logic untouched (diff verified).

#### Deviation summary

| # | What | Class |
|---|---|---|
| 1 | Example cell k=1: −2.42421 printed for true −2.414214 (digit typo; conjugate cell k=7 correct) | **A** |
| 2 | validate() oracle fftCooleyTookey silently wrong for non-power-of-two N (drops x[N−1] at odd N) | **D** |
| 3 | correctFft heap-buffer-overflow WRITE at odd N ≥ 5 (baseline.hpp:35; silent at -O2) | **D** |
| 4 | correctFft UB shift-by-32 at N=1 (baseline.hpp:49; output correct on x86) | **D** |
| 5 | Prompt states no N precondition while oracle requires power-of-two N (latent in stock pipeline, exposed by thesis enhanced tests) | **B** |
| 6 | Differential blind spot: both baselines byte-identical-wrong at N=3/5 → thesis gate passed size-3 specs | **D** |
| 7 | omp/mpi prompts differ from upstream only by stripped #include lines | **F** |

Clean results worth stating: prompt convention and oracle convention **agree** (sign=−1, unnormalized, natural order) — no 06-style convention mismatch here; both baselines are exact (≤1e-9) against an independent O(N²) DFT at every power-of-two N tested on all five input classes; the 1e-4 epsilon and 1024-point random complex validation are internally consistent.

---


## Roundtrip and Cross-Family Composition

### FFT family 05-09: roundtrip & cross-family composition audit (executed)

Scope: do the five ParEval FFT oracles (`correct*` baselines) form one mutually consistent transform family, i.e. do forward and inverse compose to the identity, and where does the 1/N live? Powers of two only (N in {4,8,16}) to separate convention issues from the (separately audited) non-power-of-two domain issue.

#### Method

All artifacts live in `C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/fft_audit/roundtrip/`:
`decl.hpp`, `w05.cpp`..`w09.cpp` (one wrapper TU per benchmark; each `#include`s the REAL baseline header from `/repo` inside a private namespace, because 07/08/09 each define a colliding non-static `fftCooleyTookey`; `NO_INLINE` neutralized -- it is only an inlining attribute, `drivers/cpp/utilities.hpp:19`), `main.cpp` (harness), `ref_check.py`, `rt07_attrib.py`, `results.csv` (636 lines), `ref_results.txt` (210 REF comparisons).

Commands (receipts):

1. Compile + run against the read-only repo mount:
   `MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" -v "<scratch>/fft_audit/roundtrip:/scratch" -w /scratch pareval-thesis bash -c "g++ -std=c++17 -O2 -c w05.cpp w06.cpp w07.cpp w08.cpp w09.cpp && g++ -std=c++17 -O2 main.cpp w05.o ... w09.o -o harness && ./harness > results.csv"`
2. `.venv/Scripts/python.exe ref_check.py results.csv > ref_results.txt` -- independent pure-Python O(N^2) DFT (stdlib `complex` only; no numpy, no ParEval code). Input vectors are integer-valued and regenerated bit-identically (`INPUT_REGEN_MAXDIFF,0`).
3. `.venv/Scripts/python.exe rt07_attrib.py results.csv` -- closed-form attribution of the one failing composition.
4. Container numpy control: unavailable (`python3 -c 'import numpy'` -> NO_NUMPY), so the pure-Python reference is the sole independent control; it uniquely identified every oracle with errors <= 1.4e-13 while rejecting all rival conventions at error 10-85 (5x5 hypothesis grid, Table 1).

The 08 wrapper pre-sizes `r`/`i` exactly as the real driver does (`drivers/cpp/benchmarks/fft/08_fft_split_fft/cpu.cc:41-42,59-61`), since `correctFft` writes into them unsized (`baseline.hpp:55-58`).

#### Findings

##### 1. The oracles are ONE consistent family (clean result)

Verified conventions (Table 1; unique fit vs the reference):

- 05 `correctIfft` (baseline.hpp:61-73) = inverse DFT: positive exponent, full 1/N. Implemented as conj -> radix-2 forward fft -> conj -> scale.
- 06 `correctDft` (baseline.hpp:16-29, the `cos(angle) - i sin(angle)` at line 24) = standard forward DFT (negative exponent), unnormalized.
- 08 `correctFft` (baseline.hpp:12-59) and 09 `correctFft` (baseline.hpp:16-56) = the same standard forward FFT; their outputs are bit-identical on every test (diff exactly 0).
- 07 `correctFft` (baseline.hpp:12-55; conjugation loop lines 52-54) = conj(forward DFT). `conj(fft07(x)) == fft09(x)` bit-exactly on every test.

Compositions (Table 2): `ifft05(fft09(x))`, `fft09(ifft05(x))`, `ifft05(dft06(x))` (real inputs), `ifft05(fft08(x))`, and `dft06(Re(ifft05(X)))` (even-symmetric real spectrum X, so the ifft output is real -- imaginary residual <= 1.11e-16) are all the identity to <= 6.6e-15 at unit input scale, at every N and input class. Direction of the 06 restriction: `dft06` takes `vector<double>`, so inverse-then-forward through 06 is only defined when `ifft05`'s output is real, i.e. for conjugate-symmetric spectra -- a domain restriction inherent to the signature, not an inconsistency.

Normalization (Table 4, exact to the last bit): `fft09(delta_0) = all-ones` (error 0.0) and `ifft05(all-ones) = delta_0` (error 0.0). The 1/N lives exactly once, in the inverse (05, baseline.hpp:72). Identity is therefore possible -- and observed.

##### 2. The one non-composing member: 07 -- by spec, with a verified closed-form failure mode

`ifft05(fft07(x)) != x`: max|err| = 1 (impulse), up to 14 (realasym N=16), 10.8 (cplxasym N=16). Attribution executed, not inferred: the roundtrip output equals `conj(x[(-k) mod N])` -- the time-reversed conjugate of the input -- to <= 4.07e-14 in all 9 cells (`rt07_attrib.py`). Cause: 07's spec-mandated output conjugation ("Return the imaginary conjugate of each value"), NOT exponent sign, NOT normalization, NOT bit-reversal leftovers. Conjugating 07's output before ifft05 restores the identity to <= 6.5e-15. Classification for the composition itself: F (07 is not supposed to be a plain FFT); B for the prompt phrase "imaginary conjugate", which is non-standard wording.

Caveat: `realasym` at N=4 is accidentally even-symmetric ([-1,7,4,7]) and thus a fixed point of time-reversed conjugation -- the two 0 cells for 07 at that size are spurious passes, not agreement.

##### 3. Prompt examples vs executed oracles (Table 5) -- the inconsistencies live in the EXAMPLES

- 06: executed `correctDft([1,4,9,16])` = `[30, -8+12i, -10-4.16e-15i, -8-12i]`; the prompt example claims `[30, -8-12i, -10-0i, -8+12i]`. The example is the opposite (positive-exponent) convention -- and it is the family-inconsistent one, since the oracle's DFT- matches 05/07/08/09. Phase-0 claim CONFIRMED by execution. Class A.
- 07: executed oracle on `[1,1,1,1,0,0,0,0]` gives `{1, +2.4142135623730949}` at k=1; the example says `{1, -2.41421}`. The example equals the raw unconjugated FFT, bit-for-bit the executed 08/09 outputs -- it contradicts both the spec sentence and the oracle. The Phase-0 description ("re/im transposed at odd indices") is REFUTED: the deviation is an imaginary-sign flip (missing conjugation), not a transposition. Class A.
- 09: executed oracle gives `-2.4142135623730949 = -(1+sqrt(2))` at k=1; the example's `-2.42421` is a digit typo. CONFIRMED. Class A.
- 05 and 08: examples match their executed oracles to print precision. Class F.

##### 4. Answers to the assigned questions

1. Forward-then-inverse and inverse-then-forward: identity at machine precision for every pair that is supposed to compose (05 with each of 06/08/09, both directions where the signatures permit).
2. The three forward transforms: 08 and 09 are bit-identical; 07 equals them exactly after undoing its conjugation; 06 is the same transform computed directly (agreement <= 1.4e-13). One transform, one convention.
3. Normalization: forward unnormalized, inverse carries the full 1/N -- exactly one carrier, verified exactly.
4. The single roundtrip failure (07 with 05) is fully attributed to 07's specified conjugation via a closed-form prediction verified to 4e-14; no exponent-sign, normalization, or bit-reversal defects anywhere in the family on power-of-two sizes.

Bottom line: on powers of two the oracle family is mathematically coherent and composes to the identity; every genuine inconsistency this audit found is in the prompt EXAMPLES (06 wrong convention, 07 missing its own conjugation, 09 typo), which penalizes models that faithfully reproduce the documented example values.

---


## Affected Enhanced Specs

### Enhanced-spec enumeration and gate audit — fft/05-09

All work under `C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/fft_audit/spec_enumeration/` (scripts, probe binaries, raw probe outputs `probes/*.txt`, `gate_replica_results.jsonl`, `reconstructed_specs.json`). Repo read-only throughout.

#### 1. Exact spec composition (what a run executes)

Assembly path: `run_enhanced_tests.py:753` loads ALL lines of `thesis/results/cache/enhanced/specs.jsonl` per benchmark (`load_llm_specs`, lines 268-282, no dedupe at load), then `build_benchmark_specs` (`thesis/enhanced_tests/specs.py:558-633`) builds per benchmark: static base (sizes `[0,1,2,7]` random fill; `config.yaml:562`, `specs.py:491-505`) -> LLM seeds in file order -> deterministic mutation rounds (seed 20260709, `specs.py:116`) until `target_cases_per_benchmark: 20` (`config.yaml:569`), deduped by `spec_key`. specs.jsonl carries two generation blocks (lines 25-47 and 373-396, both spec_model glm_5_2 — refill per `llm_specs_min: 5`); after dedupe the unique LLM seeds are 05:10, 06:8, 07:9, 08:11, 09:5.

Reconstruction executed with the repo's own code (`reconstruct_specs.py`, host venv python): 20 specs per benchmark, composition 05: 4 static+10 llm+6 mutation; 06: 4+8+8; 07: 4+9+7; 08: 4+11+5; 09: 4+5+11.

Validation of the reconstruction:
- `pilot_crosscheck.py` vs `thesis/results/intermediate/pilot_001/*/enhanced_tests.jsonl` (11 models): the pilot ran exactly these 20 specs for fft/05 (only fft benchmark in the pilot), 60 records/model = 20 specs x 3 samples (`serial/omp/mpi`, `sample_0`; `config.yaml:598` execution_models). No spec in the pilot missing from the reconstruction and vice versa.
- `compare_gate_report.py` vs the frozen `thesis/results/cache/enhanced/spec_gate_report.jsonl` (dated 2026-07-31, 20 rows per fft benchmark, written by a script no longer in the repo — no references found): **100/100 agreement** in spec order, content and gate verdict class. Drivers unchanged since commit dd7676c (2026-07-14), so the frozen report ran against today's driver code.

Not executed: `specs_discarded.jsonl` (24 fft rows), `newpattern_specs.jsonl` (0 fft rows), `archive/gpt55_2026-07-09`.

#### 2. Size semantics and non-power-of-two specs

`ENHANCED_TEST_SIZE` is the input element count: length of the complex vector for 05/07/08/09 (driver fills `real`/`imag` of that length and zips them, e.g. `05/cpu.cc:61-79`), length of the real vector for 06. Sizes 0/1/2 are degenerate powers of two, not non-power-of-two: 0 = empty (radix-2 code no-ops; `log2(0)` cast is formally UB but empirically silent, probe exit 0, no UBSan report at -O1), 1 = trivial (formal UB: `>> (32-0)` shift-by-32, UBSan: "shift exponent 32 is too large" — benign on x86, results exact). Non-power-of-two sizes present in specs: **3, 5, 6, 7, 31** — 26 specs of 100 (05: 4, 06: 6, 07: 3, 08: 5, 09: 8).

#### 3. Measured baseline behavior (independent reference)

Probes: `probe.cpp` compiled per benchmark against the repo's `baseline.hpp` + `enhanced-fill.hpp` fill implementation (`g++ -std=c++17 -O2` and `-O1 -g -fsanitize=address,undefined`), inputs constructed exactly as the drivers do (fill real then imag with the spec's pattern/lo/hi). Reference: pure-Python O(N^2) DFT (negative exponent) / IDFT (positive exponent, 1/N) on built-in `complex` (`analyze_probes.py`), no ParEval code involved. Caveat: for `random`-pattern probes the rand() stream offset differs from the in-driver stream, so values are representative of the size regime, not bit-identical; all other patterns are exact reproductions.

Docker pattern used (validated): `MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" -v "<scratch>:/scratch" -w /scratch pareval-thesis bash -c "g++ ... -I /repo/drivers/cpp/benchmarks/fft/<bench> -I /repo/drivers/cpp probe.cpp -o probe && ./probe ..."`.

Key measurements (full table in `probes/`):
- **N=3 (radix-2 code, 05/07/08)**: silently wrong, ASan-clean. Both the iterative Rosetta kernel and the recursive `fftCooleyTookey` produce the IDENTICAL wrong output `[x0+x1, x0-x1, x2]` (output[2] = input[2] verbatim; receipt `probes/08_s3_random.txt`: input[2]=(5.6619,-6.0489) appears unchanged as output[2]). Deviations vs true DFT/IDFT: 05 all_same[1,2] 0.5, 05 ascending 1.12, 07 all_same[1,1] 1.0, 08 all_same 1.0, 08 random[-10,10] 13.9.
- **N=5, 7, 31**: heap-buffer-overflow (ASan, all five benchmarks' radix-2 kernels; `baseline.hpp` line 27 `b=a+k` runs past the end). In the gate/driver context this crashed in every observed run; the standalone -O2 probe at 05 N=7/N=5 survived with wrong values (exit 0) — allocation-layout luck, same UB.
- **N=6 (09 specs; 05 probed as extra)**: in-bounds but silently wrong (09 ascending: iterative dev 30.4, recursive dev 38.1, cross-disagreement 23.5 -> the two oracles disagree, so the gate catches nonzero-input N=6; zero input maps to zeros = correct).
- **06 correctDft**: exact (<1e-9) at every probed size incl. 3 and 7 — valid for all N, as expected of a direct DFT. Only its N=7 extreme_values spec is gated (fast-math stability probe fails on inf/NaN arithmetic).
- **07 `fftCooleyTookey` (the validate() oracle, `07/cpu.cc:78`) is broken at power-of-two sizes**: it conjugates at EVERY recursion level (`baseline.hpp:81-84` inside the recursive function) and skips conjugation for N<=1 (early return line 59). Measured: dev vs conj-DFT reference = 8 (N=4), 240 (N=16 ascending), 10.6 (N=32), 0.422 (N=1 random); exact at N=2 and at luck-symmetric inputs (N=8 alternating: even/odd halves constant -> sub-FFTs real -> conjugation harmless; receipt `probes/07_s8_alternating.txt` vs `07_s8_ascending_extra.txt` dev 41.4). `correctFft` (iterative+final conj, the gate's test side) is EXACT vs conj-DFT at all power-of-two probes. Receipt `probes/07_s4_random.txt`: CT[1]=conj(correctFft[3]), CT[3]=conj(correctFft[1]), CT[0] imag sign flipped.

#### 4. Gate replication (faithful, all 100 specs)

`gate_replica.py` (run in-container) drives the repo's own `build_wrapper`/`compile_and_run`/`stability_probe` (`thesis/enhanced_tests/baseline_selftest.py:256-313`, -O1, RUN_TIMEOUT=30, COMPILE_TIMEOUT=120) with the exact per-spec defines of `precompute_gates` (`run_enhanced_tests.py:492-566`, incl. `MISMATCH_REPORT_MAX=3` per config `stages.repair.feedback.mismatch_report_max_indices`). Verdict mapping as in `process_sample` (lines 604-616): probe1 != pass -> baseline_incompatible; probe2 != pass -> numerically_unstable.

Results (`gate_replica_results.jsonl`): gated 20/100.
- 05: N=7 random (crash), N=5 extreme (crash). Cross-checks: pilot live gates identical (33 baseline_incompatible records each = 11 models x 3 samples, `baseline_gate:"crash"`), frozen report identical, static selftest cache (`baseline_selftest.jsonl`) N=7 crash identical. **Pilot claim "2/20 gated, sizes 5 and 7 crash" CONFIRMED.**
- 06: N=7 extreme -> probe2 validate_fail -> numerically_unstable. All other 19 run.
- 07: 10 gated — crash N=7, N=31; validate_fail N=1 random, N=4 x5 (extreme x2/alternating/all_same/random), N=16 ascending, N=32 random. The validate_fails are two-oracle disagreements in which the DISCARDED baseline (`correctFft`) is the mathematically correct side (except the inf/NaN extreme pair); the gate protects models here by accident and at the cost of throwing away 8 legitimate power-of-two specs.
- 08: crash N=5 ascending, N=7 random.
- 09: crash N=5, N=7 x2; validate_fail N=6 ascending, N=6 random (two-oracle disagreement — genuine protection).

**The dangerous silent class — specs that run with a wrong oracle (gate structurally blind):** 05 N=3 x2 (self-comparison of one function can only fail by crash), 07 N=3 x1 and 08 N=3 x3 (the gate IS a two-implementation differential there, but both implementations produce identical garbage at N=3, receipt above). 6 specs total. 09's non-power-of-two survivors are all zero-input (all_zeros, or all_same without value_range = midpoint(-1,1) = 0, `enhanced-fill.hpp:188`) and therefore benign: zeros map to zeros = the correct answer.

#### 5. Realized impact (pilot) and projection

Pilot fft/05 fail records (all of them): gemini_36_flash, mpi, specs (3, all_same), (3, ascending), (4, extreme_values). The sample's source (`pilot_001/gemini_36_flash/sources/gemini_36_flash__fft__05_fft_inverse_fft__mpi__sample_0/generated-code.hpp` lines 55-70) contains a direct O(N^2) IDFT fallback for `n % size != 0` — the mathematically correct inverse DFT for any N. At N=3 with 4 mpi ranks it produces the TRUE IDFT, which mismatches the silently-wrong radix-2 oracle -> **2 false 'fail' verdicts already recorded in the pilot**. The (4, extreme) fail is inf/NaN-handling divergence at ±DBL_MAX inputs (comparison semantics: `abs(a-b) > tol` is false for NaN and for inf-inf, so NaN/inf self-comparisons pass; only inf-vs-finite mismatches fail) — a degenerate-input verdict, not a model-quality signal. All 10 other models pass at N=3, i.e. their generated code reproduces the radix-2 garbage (baseline-cloning agreement).

Projection to a full run (fft 05-09, 3 execution models, 1 sample each): 6 wrong-oracle specs x 3 samples = up to 18 unreliable records per model, realized whenever a model implements any valid-for-all-N algorithm (as one pilot model demonstrably did); additionally 8 x 3 = 24 records per model discarded as baseline_incompatible for 07 at power-of-two sizes solely due to the validate-oracle bug (coverage loss, no wrong verdicts — baseline_incompatible is never counted against a model).

#### 6. Commands (receipts)

1. `.venv/Scripts/python.exe reconstruct_specs.py` — spec reconstruction via repo's `build_benchmark_specs` + `load_config` (stdout in transcript; output `reconstructed_specs.json`).
2. `.venv/Scripts/python.exe pilot_crosscheck.py` — pilot vs reconstruction (20/20 for fft/05; statuses per spec incl. 33x baseline_incompatible at N=5/7).
3. `MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" -v "<scratch>:/scratch" -w /scratch pareval-thesis python3 /scratch/gate_replica.py` — 100 faithful gate probes (`gate_replica_results.jsonl`).
4. In-container probe builds: `g++ -std=c++17 -O2 -DUSE_SERIAL "-DDRIVER_PROBLEM_SIZE=(1<<4)" -DBENCH_XX -I /repo/drivers/cpp/benchmarks/fft/<bench> -I /repo/drivers/cpp probe.cpp -o probe_XX` plus `-O1 -g -fsanitize=address,undefined` variants; `bash run_probes.sh` -> `probes/*.txt` (39 cases x 2 builds).
5. `.venv/Scripts/python.exe analyze_probes.py` — deviations vs independent pure-Python O(N^2) DFT/IDFT (one display glitch for the 08 N=3 1e308 row's cross-column was re-verified inline: strict cross-dev = inf from inf-inf, while under the driver's NaN-masked comparison the two sides count as equal — consistent with the observed gate pass).
6. `.venv/Scripts/python.exe compare_gate_report.py` — replica vs frozen report: agree=100 disagree=0.

#### 7. Summary counts

| benchmark | total specs | non-pow2 specs | gated today | silently-wrong RUNNING | wrong-verdict carriers into full run |
|---|---|---|---|---|---|
| fft/05_fft_inverse_fft | 20 | 4 (3,3,5,7) | 2 (crash 5,7) | 2 (N=3 x2) | 2 (realized in pilot: 2 false fails) |
| fft/06_fft_dft | 20 | 6 (3x2, 7x4) | 1 (numerically_unstable 7-extreme) | 0 | 0 |
| fft/07_fft_fft_conjugate | 20 | 3 (3,7,31) | 10 (crash 7,31; divergence 1,4x5,16,32) | 1 (N=3) | 1 (+8 specs/model coverage lost to validate-oracle bug) |
| fft/08_fft_split_fft | 20 | 5 (3x3,5,7) | 2 (crash 5,7) | 3 (N=3 x3) | 3 |
| fft/09_fft_fft_out_of_place | 20 | 8 (3x2,5,6x3,7x2) | 5 (crash 5,7x2; divergence 6x2) | 0 (N=3/6 survivors are zero-input) | 0 |
| **total** | **100** | **26** | **20** | **6** | **6 specs (x3 execution models per model)** |

> **Adversarial verification (V2: N-domain + specs enumeration): CONFIRMED.** Corrections/precision notes: Minor, none load-bearing: (a) 08 N=3 spec-input [-1.667,-0.333,1.0]: baseline middle value is -1.334 (= x0-x1), not -1.333 as transcribed; the claimed max per-bin diff 3.21 is exact (3.21491). (b) Claim that at plain -O2 the standalone N=5/7 overflow of 08/09 "was SILENT (exit 0, garbage output)": in MY standalone probes all four radix-2 baselines ABORT at -O2 (rc=134, glibc "malloc(): corrupted top size") on every input class at N=5/7 — the silent-survival observation is allocation-layout-dependent and did not reproduce here; the underlying classification (OOB heap write) is ASan-proven either way, and gate/pilot drivers crash, as the claim itself records. (c) 07 parenthetical "exact only at N<=2": fftCooleyTookey at N=1 with a COMPLEX input returns x instead of conj(x) (my cplx case: dev 0.4), so N<=2 exactness holds only for real/zero inputs at N=1; the claim is elsewhere self-consistent (it lists size 1 among the 8 validate_fail specs and notes the early return skips conj). (d) Input-specific dev figures I could not replicate exactly because they depend on the claimants' probe inputs (05 N=3 realasym 1.53 — mine 1.17 on my own realasym; 07 cooley dev 8@N=4 / 240@N=16 / 10.6@N=32 — mine 2@N=4 cplx, 31.4@N=16 asc, 271@N=32 asc; 08 N=3 random[-10,10] dev 13.9): same sign and order, qualitative classification identical; treat the exact numbers as probe-input-specific. (e) "agrees with pilot live gates": pilot's enhanced stage ran ONLY fft/05 within this family (660 records) — agreement is fully verified there (0/642 mismatches) but is not checkable for 06-09 from pilot data.


---


## Pilot Data Reconciliation (fft/05, frozen pilot_001 records)

### Reconciliation: measured fft/05 domain limits vs frozen pilot_001 enhanced records

Scratch dir: `C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/fft_audit/reconcile05/` (catalog.py, trajectory.py, probe_baseline.cpp, ref_idft.py, repro_mpi.sh, gatesrc/generated-code.hpp).

#### 1. Frozen record catalog (all 7 run dirs)

Command: `.venv/Scripts/python.exe .../catalog.py` over `thesis/results/intermediate/{pilot_001,pilot_001__{combined,static,test}_feedback__iter{1,2}}/<model>/enhanced_tests.jsonl` (11 models). 1620 fft/05 records: **1383 pass, 162 baseline_incompatible, 54 build_failed, 21 fail**. 20 distinct specs; sizes {0,1,2,3,4,5,7,8,16,4096}.

**Cross-model-identical (harness signal):**
- `(5, extreme_values)` and `(7, random)` are `baseline_incompatible` with `baseline_gate: "crash"` in **all 81 sample-slots** — 100% cross-model, pure harness/oracle property.
- Every `fail` record carries the **identical 3-spec signature** {(3, all_same, value_range [1,2]), (3, ascending, [-1,1]), (4, extreme_values)}, `exit_code: 0` ("Validation: FAIL" marker).

**Model-specific:** the fail signature occurs for exactly 2 of ~45 mpi sample-slots: `gemini_36_flash__...__mpi__sample_0` (pilot_001, combined_iter1, combined_iter2, static_iter1, static_iter2 — 5 different sources by md5, all repairs kept failing) and `deepseek_v4_pro__...__mpi__sample_0` (combined_iter1, combined_iter2 — its pilot_001 source didn't compile). No serial or omp sample ever failed. The 54 build_faileds are 3 mpi samples × 18 runnable specs (uniform per sample, spec-independent).

#### 2. Measured baseline domain behavior (fft/05 correctIfft, drivers/cpp/benchmarks/fft/05_fft_inverse_fft/baseline.hpp)

Probe: `probe_baseline.cpp` includes the repo baseline verbatim; container build `MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" -v "<scratch>:/scratch" -w /scratch pareval-thesis bash -c "g++ -std=c++17 -O2 -I /repo/drivers/cpp probe_baseline.cpp -o probe && ./probe <case>"`; sanitizer variant `-O1 -g -fsanitize=address,undefined`. Independent reference: pure-Python O(N²) IDFT (`ref_idft.py`, builtin complex, convention x[n] = (1/N)·Σ X[k]e^{+2πikn/N}; no ParEval code).

| N (spec sizes present) | Measured baseline behavior | Receipt |
|---|---|---|
| 0, 1 | no-op / identity, correct; no sanitizer finding | probe n0/n1, ASan exit 0 |
| 2, 8, 16 (and 4096 by extension) | exact IDFT — matches Python reference to ~1e-16; N=8 matches the prompt example `{0.5,0},{0.125,0.301777},...` | probe n2/n8ex vs ref_idft.py |
| **3** | **silently wrong, no UB**: all_same(1.5+1.5i)×3 → `[1+1i, 0, 0.5+0.5i]`, true IDFT = `[1.5+1.5i, ~0, ~0]`; ascending (-1,0,1 both parts) → `[(-1/3,-1/3),(-1/3,-1/3),(1/3,1/3)]`, true = `[0, -0.2113-0.7887i, -0.7887-0.2113i]`. ASan clean. | probe n3same/n3asc, ref_idft.py, ASan exit 0 |
| **5, 7** | **heap-buffer-overflow**: ASan `WRITE of size 16` at `baseline.hpp:30` (`x[b] = t * T;`), "0 bytes after 80-byte region" at N=5 ⇒ b==N. Environment-dependent manifestation: silent corruption in the minimal -O2 probe (exit 0, garbage), **SIGABRT `malloc(): corrupted top size`, exit 134** in the exact gate build. | ASan runs; gate replication below |
| 4, 16 with extreme_values (±DBL_MAX) | in-domain size, **degenerate values**: exact IDFT is finite (`[0,0,-(M+Mi),0]` at N=4, unit-scaled Python check) but every double implementation overflows; baseline N=4 → `[(-nan,nan),(0,-0),(-inf,-inf),(0,-0)]`, N=16 → alternating `(-nan,nan)`/`(0,-0)` with `[8]=(-inf,-inf)` | probe n4ext/n16ext, ref_idft.py |

**Gate replication** (exact runner recipe: serial-driver.cc + cpu.cc + wrapper forwarding ifft→correctIfft, `g++ -std=c++17 -O1 -DUSE_SERIAL -DDRIVER_PROBLEM_SIZE=(1<<4) -DENHANCED_TEST_SIZE=<n> -DENHANCED_FILL_PATTERN=<id> [LO/HI]`, per thesis/evaluation/run_enhanced_tests.py:526+550 and thesis/enhanced_tests/baseline_selftest.py:284-293): size 5 pat 6 → exit 134 crash; size 7 pat 0 → exit 134 crash; size 3 (both fills) and size 4 pat 6 → `Validation: PASS`. **Matches frozen gates exactly and shows why N=3 and N=4-extreme are NOT gated: the gate compares the oracle against itself.** The fast-math stability probe can't catch these either — same algorithm on both sides.

#### 3. Why exactly these two samples fail — sources + binary re-runs

- `gemini_36_flash mpi` (pilot_001 source, lines 55–70): for `n % ranks != 0` (n=3, ranks=4 per config.yaml:604 `mpi_ranks: 4`) computes a **direct O(N²) IDFT, positive exponent, /n** — the mathematically true inverse DFT; for `n % ranks == 0` (n=4) an exact block-DFT recombination. All 5 repaired versions retain a DFT fallback (grep receipt: `angle = 2.0 * PI * k * j / n` still present in static_iter2 source line 66).
- `deepseek_v4_pro mpi` (combined_iter2 source, lines 22–31): pure O(N²) true IDFT (`exp(+iθ)`, /N) for all N. iter1 identical math (line 25–26).
- Passing control `claude_fable_5 mpi`: conj → `fft(x)` → conj/N, calling the **prompt's forward-declared fft() helper, which links to the baseline's own radix-2 fft** — bit-identical to the oracle everywhere, including its N=3 garbage.

**Verdict-by-verdict reproduction of the frozen binaries** (`repro_mpi.sh`; exact runner build `mpicxx -std=c++17 -O3 -DUSE_MPI -I /repo/drivers/cpp -I /repo/drivers/cpp/models -I <frozen sources dir> "-DDRIVER_PROBLEM_SIZE=(1<<4)" -DENHANCED_TEST_SIZE=<n> -DMISMATCH_REPORT_MAX=3 -DENHANCED_RUNTIME_FILL models/mpi-driver.cc cpu.cc`; launch `mpirun -np 4 <bin> 1` with `ENHANCED_FILL_PATTERN` [+RANGE_LO/HI] env, per run_enhanced_tests.py:325-333,392 and specs.py:420-450): 15/15 verdicts reproduce — gemini and deepseek FAIL at 3-all_same, 3-ascending, 4-extreme and PASS at 16-extreme and 8-all_same; fable control passes all 5.

**Mechanism per failing spec** (driver predicate cpu.cc:93: fail iff |Δre|>1e-4 or |Δim|>1e-4; NaN comparisons never fail):
- N=3 all_same: oracle [0]=1+1i vs model 1.5+1.5i (Δ=0.5), [2]=0.5+0.5i vs ~0. **Model correct, oracle wrong.**
- N=3 ascending: all 3 indices differ (Δ up to 0.79). **Model correct, oracle wrong.**
- N=4 extreme: single decisive index 3 — oracle `(0,-0)` vs model `(+inf, nan)`: |0−inf|=inf → FAIL. Indices 0,1 have NaN on one side (auto-pass), index 2 is −inf vs −inf (Δ=NaN, auto-pass). Both sides are overflow garbage relative to the finite exact answer; the verdict is an inf-placement lottery.
- N=16 extreme passes for everyone: every index pairs a NaN with something → auto-pass. The spec has zero discriminative power.

The spec generator *intended* to expose the oracle: the frozen (3,all_same) spec's rationale reads "Non-power-of-2 size causes log2(3) truncation to 1, producing incorrect bit-reversal width and butterfly stages" — the harness then counted the resulting mismatch against the model.

#### 4. build_failed records (54)

Frozen `enhanced_build_groups.jsonl` build_stderr: deepseek_v4_pro pilot_001 mpi — leaked chain-of-thought prose in the source ("error: 'But' was not declared in this scope", generated-code.hpp:13); deepseek_v4_flash cf_i1 mpi — `MPI_Type_commit(&MPI_DOUBLE_COMPLEX)` on a predefined-datatype macro; claude_opus_5 sf_i2 mpi — "'ifft' was not declared in this scope" (function not emitted usably). Genuine model-side compile errors, uniform across all 18 runnable specs, unrelated to domain limits. Class F.

#### 5. Classification (legend A–F)

- (5,extreme_values), (7,random) gates: **D** — oracle valid only for power-of-2 N; out-of-bounds write (UB) at N=5/7; the crash-gate correctly quarantined them, no model was penalized.
- (3,all_same), (3,ascending) fails: **D** (oracle) + **E** (models) — oracle silently wrong outside power-of-2; the two failing samples compute the legitimate true IDFT and are **falsely failed for being more correct than the oracle**; every passing sample reuses the shared fft() helper and reproduces the oracle's garbage bit-for-bit (matching-the-bug is rewarded, independent math is punished).
- (4,extreme_values) fail / (16,extreme_values) pass: **C/D (value-domain)** — comparison invalid for inputs whose DFT intermediates overflow double; NaN-tolerant predicate turns the verdict into an inf-placement lottery (fails at N=4 index 3, auto-passes everyone at N=16). Not a size-domain issue.
- 05 prompt example: **F** — N=8 example verified against the independent reference to ~1e-16.
- build_faileds: **F** — real generated-code defects.

#### 6. Reconciliation answer

The measured boundaries explain 100% of the frozen fft/05 pattern, reproduced verdict-for-verdict, **but the story needs two mechanisms, not one**: (a) the size-domain limit (power-of-2 validity: silent wrongness at N=3, heap overflow at N=5/7) explains both gates and 2 of 3 fails per failing sample; (b) the value-domain degeneracy (±DBL_MAX overflow + NaN-tolerant predicate) explains the third fail at in-domain N=4. The prior Phase-0 attribution ("silently-wrong baseline at N=3; 5/7 gated") is confirmed as far as it goes but was **incomplete on the (4,extreme_values) fail**, which is not a non-power-of-two domain violation. No fail in the frozen 05 data is a genuine model bug; conversely 3 samples' build_faileds are genuine model defects correctly recorded.

---


## Common-Cause Analysis

### Common-cause analysis: example defects in ParEval FFT family 05–09

Scope: determine whether the defective prompt examples of 06/07/09 share one generating mechanism; characterize 07's "transposition"; test the Rosetta-single-source hypothesis; test whether 05/08's clean examples are informative; verify upstream inheritance. All numbers computed with an independent pure-Python O(N^2) DFT (built-in `complex`, host venv `C:/Users/jerab/Desktop/ParEval-thesis/.venv/Scripts/python.exe`); no ParEval code used as reference. Scratch dir: `C:/Users/jerab/AppData/Local/Temp/claude/C--Users-jerab-Desktop-ParEval-thesis/632014e8-b691-476d-9f45-6ee30cca3c51/scratchpad/fft_audit/common_cause/` (contains `common_cause.py`, `probes.cpp`, `gen-prompts-05af9f8.json`).

Notation: `DFT(s,n)` = X[k] = n * sum_n x[n] exp(s*2πi nk/N); sign s ∈ {−,+}, norm n ∈ {1, 1/N, 1/√N}. Matching tolerance = printed 6-sig-fig precision (|a−b| ≤ 5e-6·max(1,|b|)), matching C++ default ostream precision.

#### Q3 first: the canonical example, from mathematics

Computed `DFT(−,1)` of `[1,1,1,1,0,0,0,0]`, formatted `%.6g` (script `common_cause.py`, section Q3):

```
{4,0} {1,-2.41421} {0,0} {1,-0.414214} {0,0} {1,0.414214} {0,0} {1,2.41421}
```
with exact identities X[1] = 1 − (1+√2)i (1+√2 = 2.4142135624) and X[3] = 1 − (√2−1)i (√2−1 = 0.4142135624), verified to 1e-12. This is the classic FFT demo vector. **In-repo receipt for the Rosetta source (no browsing needed):** `drivers/cpp/benchmarks/fft/05_fft_inverse_fft/baseline.hpp:11` — comment `from https://rosettacode.org/wiki/Fast_Fourier_transform#C++` above the iterative DIF kernel; the byte-same kernel is `correctFft` in 07 (baseline.hpp:12–55), 08 (:12–59) and 09 (:16–56).

Cell-by-cell comparison of this canonical vector against the printed examples (script output):
- ex07 == DFT(−,1): **0 differing cells** (i.e. 07's example is the *unconjugated* transform, despite the prompt text demanding a conjugate).
- ex08 == DFT(−,1): **0 differing cells** (correct: 08 asks for a plain FFT).
- ex09 == DFT(−,1): differs **only at cell 1** (printed −2.42421 vs true −2.41421; |printed|−(1+√2) = **+0.00999644**, one digit '1'→'2' in the 3rd significant digit; ex09's own k=7 cell prints the correct 2.41421).
- ex05 == conj(DFT(−,1))/8: **exact** (0.301777 = (1+√2)/8, 0.0517767 = (√2−1)/8) — the mathematically correct IDFT of the same vector, since the input is real.

So 4 of 5 examples are the same Rosetta vector under identifiable, benchmark-appropriate (05, 08) or *missing* (07) or *corrupted* (09) derivations. 06 uses a different input entirely.

#### Q1: is there ONE transformation that generates all defective examples? — NO (computed)

Catalog: 18 candidates = {sign −,+} × {norm 1, 1/N, 1/√N} × {plain, conj, re/im-swap}, applied to each example's own input, matched at printed precision (`common_cause.py`, section Q1). Results:

| example | matching transformations |
|---|---|
| 06 `[1,4,9,16]→[30+0i,-8-12i,-10-0i,-8+12i]` | `DFT(+,1)` ≡ `conj(DFT(−,1))` (identical on real input; also ≡ unnormalized IDFT) |
| 07 | `DFT(−,1)` ≡ `conj(DFT(+,1))` |
| 09 (strict) | **NONE of 18** (typo cell) |
| 09 (typo cell excluded) | `DFT(−,1)` ≡ `conj(DFT(+,1))` |
| 05 | `DFT(+,1/N)` ≡ `conj(DFT(−,1/N))` — the correct IDFT |
| 08 | `DFT(−,1)` — the correct forward FFT |

**Intersection over the defective trio {06, 07, 09}: EMPTY.** 06 requires the *positive*-exponent convention; 07 and 09 are the *negative*-exponent transform. Both inputs are real with nonzero, sign-asymmetric imaginary spectrum cells, so DFT(+) ≠ DFT(−) on both — the two hypotheses are mutually exclusive. A forward/inverse confusion also fails as a common cause: unnormalized IDFT matches 06 but not 07/09; and no swap variant matches anything.

**What the defects DO share (provenance, executed):** compiled `probes.cpp` against the shipped baselines and ran in Docker:

```
MSYS_NO_PATHCONV=1 docker run --rm -u 0 -v "C:/Users/jerab/Desktop/ParEval-thesis:/repo:ro" \
  -v "<scratch>/fft_audit/common_cause:/scratch" -w /scratch pareval-thesis \
  bash -c "g++ -std=c++17 -O2 -I /repo/drivers/cpp/benchmarks -I /repo/drivers/cpp probes.cpp -o probes && ./probes"
```
Token-level results (C++ default ostream precision, exactly the prompts' formatting):
- `05 correctIfft(ROS)` → `[{0.5,0}, {0.125,0.301777}, {0,-0}, {0.125,0.0517767}, {0,-0}, {0.125,-0.0517767}, {0,-0}, {0.125,-0.301777}]` — **byte-equal to prompt05 including all three signed-zero `{0,-0}` cells.** The 05 example was generated by this code (or code producing bit-identical output).
- `05 fft(ROS)` (the verbatim Rosetta kernel) → `[{4,0}, {1,-2.41421}, {0,0}, {1,-0.414214}, {0,0}, {1,0.414214}, {0,0}, {1,2.41421}]` — **byte-equal to prompt07's example string** (and to 08's values, and to 09's except the typo cell).
- `07 correctFft(ROS)` (the conjugated perf-reference) → `[{4,-0}, {1,2.41421}, {0,-0}, {1,0.414214}, {0,-0}, {1,-0.414214}, {0,-0}, {1,-2.41421}]` — differs from prompt07 in all four odd cells AND in the zero signs of the even cells. `07 fftCooleyTookey(ROS)` (validate oracle) → `[{4,-0}, {2.41421,-1}, {0,0}, {-0.414214,1}, {0,-0}, {-0.414214,-1}, {0,-0}, {2.41421,1}]` — matches nothing. **Conclusion: 07's example is a verbatim copy of the plain forward-FFT output; the conjugation demanded by the prompt text was never applied to it.**
- `08 correctFft(ROS)` split → `r: [4, 1, 0, 1, 0, 1, 0, 1] i: [0, -2.41421, 0, -0.414214, 0, 0.414214, 0, 2.41421]` — **byte-equal to prompt08.**
- `09 correctFft(ROS)` and `09 fftCooleyTookey(ROS)` both → `[{4,0}, {1,-2.41421}, ...]` — **byte-equal to prompt09 except cell k=1** (code prints −2.41421, prompt says −2.42421). The typo is transcriptional, not computational.
- `06 correctDft([1,4,9,16])` → `[30+0i, -8+12i, -10-4.1638e-15i, -8-12i]`; a mirrored sign=+ loop → `[30+0i, -8-12i, -10+4.1638e-15i, -8+12i]`; `conj(oracle)` → `[30-0i, -8-12i, -10+4.1638e-15i, -8+12i]`. The prompt's values (30, −8−12i, −10, −8+12i) match sign=+ exactly, but **no tested C++ candidate reproduces the exact token `-10-0i` together with `30+0i`**. Optional numpy control (installed transiently in the container, numpy 2.5.2): `np.fft.ifft([1,4,9,16])*4` = `[30.+0.j, -8.-12.j, -10.+0.j, -8.+12.j]` — values exact, but imag zeros are `+0` at k=0 and k=2; `np.conj(np.fft.fft(...))` gives `-0.j` at both. The mixed `+0i`/`-0i` pattern of the prompt matches neither. The `-0i` token proves machine generation (nobody hand-writes −0), but the exact generator of 06's example is **Unclear**. Note also 06's example uses `a+bi` notation while 05/07/09 use `{re,im}` braces and 08 uses split arrays — a formatting break consistent with 06's example coming from a different tool/source than the Rosetta-derived quartet.

**Answer Q1:** the examples were *not* produced by one convention error. Common causes exist at two other levels: (a) 05/07/08/09 all derive from one external source (the Rosetta C++ FFT kernel and its canonical input, cited in-repo), with 07's defect = derivation step omitted and 09's = one-digit copy error; (b) see Q5 — the two newest defective examples entered in the same commit. 06's defect is an independent sign-convention error on a different input.

#### Q2: is anything actually re/im-transposed in 07? — No; the "transposition" is an oracle artifact

- The **example itself contains no transposition**: it is exactly `DFT(−,1)` of the input (0 differing cells, token-identical to the shipped Rosetta kernel's output). Its defect is a *missing conjugation*, i.e. a "conjugate" step not applied — consistent with a copy/paste of the base FFT example, and inconsistent with a component swap (a swap of the true conjugated output `{1,2.41421}` would give `{2.41421,1}`, which is not what is printed).
- The transposed **appearance** arises only when comparing example vs the validate oracle (`fftCooleyTookey` with `conj` inside the recursion, baseline.hpp:81–84). Replicated the oracle in Python (`fft_cooley_07` in `common_cause.py`) and byte-confirmed against the Docker run. Per-cell relation on the Rosetta input: oracle[k] = example[k] at even k; at odd k oracle = **−swap** (= −i·conj) of the example at k=1,5 and **+swap** (= +i·conj) at k=3,7. A single global swap fails (differs at cells 0,1,5). So even on this input it is an *alternating* ±swap, not a transposition.
- On random complex N=8 inputs (3 trials, seed shown in script) the oracle equals `conj(DFT−)` exactly on output cells **{0,2,4,6}** and matches *none* of {DFT±, conj, ±swap, ±i·conj} on odd cells (8/8 or 4/8 mismatches for every candidate). Closed-form progression (computed): N=2 → conj(DFT), N=4 → DFT(+), N≥8 → not a DFT under any convention. The per-level conjugation flips the effective twiddle sign at alternating recursion depths.
- Why it *looks* like a swap here: the true odd cells are {1, ±(1+√2)} and {1, ±(√2−1)}; multiplying by ±i·conj exchanges the component magnitudes, mimicking a transposition on exactly this input.

**Answer Q2:** consistent with a 'conjugate' misunderstanding twice over — (i) the example writer skipped the conjugation entirely; (ii) the oracle author inserted the conjugation at every recursion level instead of once at the top (contrast 07 `fftCooleyTookey` lines 81–84 vs 09's byte-same function without them). No evidence anywhere of a deliberate or accidental re/im component swap.

#### Q4: are 05 and 08 only accidentally consistent? — No; their examples are discriminating

Computed each example's expected output under the alternative conventions (`common_cause.py`, section Q4). Differing cells at printed precision:

| alternative | 05 (vs printed) | 08 (vs printed) |
|---|---|---|
| oracle convention | 0 (match) | 0 (match) |
| sign flip | 4 cells (1,3,5,7) | 4 cells (1,3,5,7) |
| fwd/inv confusion | 5 cells | 5 cells |
| wrong norm (1/√N, unnorm / 1/N) | 5 cells | 5 cells |
| conj (07-style) | n/a (=sign flip) | 4 cells |
| re/im swap | 5 cells | 5 cells |

The shared input `[1,1,1,1,0,0,0,0]` is real but time-asymmetric, so its spectrum has nonzero, sign-asymmetric imaginary parts at k=1,3,5,7; every tested confusion visibly changes ≥4 of 8 cells. **The 05/08 examples are fully capable of exposing the 06/07-style confusions, and they match their oracles — their cleanliness is a substantive result, not a vacuous one.** One quantified blind spot: because the example input is real, errors differing only by input conjugation are invisible — demonstrated: `conj(DFT−(x))/N` ≡ true IDFT(x) exactly on the real example input (max diff 0) but differs at 7/8 cells on a complex input. The validate() harnesses use complex random inputs, so this limits only the example's evidential power, not the grading.

#### Q5: upstream inheritance — verified end-to-end (not just spot-checked)

**Prompts.** Byte-compared all 15 thesis entries (`thesis/prompts/generation-prompts-thesis.json`) against `prompts/generation-prompts.json` (heredoc script, output in transcript): all five `serial` entries **byte-identical** (408/242/314/355/327 bytes); all `omp`/`mpi` entries differ **only** by the upstream leading `#include <omp.h>\n\n` / `#include <mpi.h>\n\n` (verified `a.endswith(b)` suffix relation, first diff at offset 0). Defective example fragments present in **7/7 upstream variants** (serial/omp/mpi/mpi+omp/kokkos/cuda/hip) for each benchmark, and in 3/3 thesis variants.

**Baselines.** `git log --follow --oneline -- drivers/cpp/benchmarks/fft/<b>/baseline.hpp` → exactly one commit for all five: `05af9f8` "Update Prompts and Add Some Drivers (#10)", author Daniel Nichols <dando18studios@gmail.com>, **2024-01-16** (upstream ParEval maintainer; remote `upstream = https://github.com/parallelcodefoundry/ParEval.git`). Working-tree blob identity: `git hash-object` of each file equals `git rev-parse 05af9f8:<path>` for all five (hashes 34b33e91…/64f58a27…/1669c553…/6df387e1…/ef38d612…). First thesis-authored commit: `dbcd34c` (jerabek-niklas, **2026-06-04**) — the defects predate the thesis fork by >2 years. Nothing thesis-introduced.

**Defect introduction timeline (git archaeology):**
- `4c9276c` "Refactor Drivers (#6)" (pre-2024-01-16): fft family had **3** members — `05_fft_inverse_fft`, `06_fft_fft_conjugate` (today's 07), `07_fft_split_fft` (today's 08). The conjugate benchmark's example was **already the unconjugated Rosetta output** (pickaxe `git log -S"Return the imaginary conjugate" --reverse` → first hit 4c9276c). 05's and 08's examples already byte-equal to today's.
- `05af9f8` (2024-01-16, PR #10): renumbering to 5 members; **adds `06_fft_dft` with the sign-flipped example and `09_fft_fft_out_of_place` with the typo** (pickaxe `-S"2.42421"` and `-S"[30+0i, -8-12i, -10-0i, -8+12i]"` → first hit 05af9f8 for both); adds all five `baseline.hpp` including 07's conj-in-recursion oracle.
- `e865425` (2024-01-21, PR #15): renames 07's function `fft`→`fftConjugate`, rewords 09 ("discrete fourier transform"→"fourier transform"); **examples untouched** — verified by tracing the serial texts across 05af9f8/e865425/da414f1/767980f/9a9220b: the example strings are byte-stable from 05af9f8 to HEAD.

#### Classification (legend A–F), common-cause layer

- **06 example: A (+B, unstated sign convention).** Generated under the opposite-sign convention (≡ conj ≡ unnormalized inverse; indistinguishable on real input). Machine-generated (signed `-0i` token) but exact generator Unclear; not part of the Rosetta quartet (different input, different notation).
- **07 example: A (+B for 'imaginary conjugate' wording; the oracle's C is a separate, independently introduced defect).** Verbatim copy of the plain forward-FFT output; the stated conjugation was never applied to the example. No transposition.
- **09 example: A.** One-digit transcription typo in a copy of the correct forward-FFT output.
- **05, 08 examples: F**, and demonstrably informative (Q4).
- **Common cause:** not one mathematical transformation. Two documented shared roots: single external source (Rosetta C++ FFT kernel + canonical input, cited at 05 baseline.hpp:11) for 05/07/08/09, and single upstream commit 05af9f8 introducing both newer defective examples plus all baselines. The three defects are three *independent* human errors (sign convention, omitted derivation step, digit typo) committed while writing example blocks that were never regenerated from the shipped oracles — except in 05 and 08, whose examples *were* generated from the shipped code (token-proof incl. signed zeros).

#### Commands run (receipts)

1. `mkdir -p <scratch>/fft_audit/common_cause`; `ls` of prompt dirs.
2. Host-venv Python heredocs: enumerate fft entries in both JSONs; byte-compare all 15 thesis-vs-upstream pairs; dump serial texts.
3. `Read` of all five `drivers/cpp/benchmarks/fft/*/baseline.hpp`.
4. `common_cause.py` (in scratch): independent O(N^2) DFT, 18-candidate convention catalog per example, canonical-vector computation, 07-oracle Python replica + per-cell relation table + random-input tests, Q4 discrimination tables, 05-as-conj(Rosetta)/8 check.
5. `probes.cpp` (in scratch) compiled/run in Docker (command quoted above): token-level baseline provenance for 05/06/07/08/09.
6. Optional numpy control: `docker run --rm -u 0 pareval-thesis bash -c "pip install --quiet --break-system-packages numpy; python3 -c '...'"` (numpy 2.5.2; container python3 otherwise has no numpy).
7. Git: `git log --follow --oneline -- <each baseline.hpp>`; `git log -1 --format=... 05af9f8`; `git rev-list --max-parents=0 HEAD`; `git remote -v`; `git log --oneline -- prompts/generation-prompts.json`; `git show 05af9f8:prompts/generation-prompts.json` (saved to scratch) + fft-entry comparison vs HEAD; serial-text trace across 05af9f8/e865425/da414f1/767980f/9a9220b; `git show 4c9276c:prompts/generation-prompts.json` fft dump; pickaxe `git log -S<fragment> --reverse` for the three defect strings; `git hash-object` vs `git rev-parse 05af9f8:<path>` for all five baselines; author/date queries for dbcd34c, e865425, 9a9220b, dc89f2d.

No repo files were modified; all writes confined to the scratch directory.

---

## Cross-Family Consistency

| benchmark | operation | prompt convention | oracle convention | normalization | example correct | multi-input check | roundtrip | valid N domain | classification |
|---|---|---|---|---|---|---|---|---|---|
| 05_fft_inverse_fft | inverse DFT, in-place, complex | text silent; example pins sign=+1, 1/N (match 3.05e-07 = 6-sig-fig rounding) | sign=+1, 1/N on inverse (via conj∘fft∘conj/N) | 1/N on inverse — prompt and oracle agree | **yes** (8/8 cells) | 25/25 pow2 cases match (+1, 1/N); complex/real-asym inputs pin the sign uniquely | composes: ifft05∘fft09 = fft09∘ifft05 = Id ≤ 5.7e-15 | N = 2^m only; N=3 silently wrong, N=5/7 heap-OOB write, N=1 formal UB | D (domain) + F (example fine) |
| 06_fft_dft | forward DFT, real → complex, O(N²) direct | text silent; example = sign=+1 unnorm (≡ conj(DFT⁻) ≡ unnorm IDFT on real input — not uniquely attributable) | sign=−1, unnorm (unique over 32 cases) | none / none — agree | **no** — k=1, k=3 conjugated (`-8-12i` vs oracle `-8+12i`) | 32/32 cases match (−1, none), incl. N=3,5,7 — full-domain O(N²) | composes: ifft05∘dft06 = Id ≤ 8.8e-15 | **all N ≥ 1** (radix-2 problem does NOT apply) | **A** (example) + B (text silent) |
| 07_fft_fft_conjugate | per text: FFT then conjugate; perf ref = conj(DFT⁻); **validate oracle ≠ DFT for N≥8** | text: FFT+conj (sign unstated, "imaginary conjugate" nonstandard); example = plain **un**conjugated DFT⁻ | correctFft = conj(DFT⁻) (pow2); fftCooleyTookey: N=2 conj(DFT⁻), N=4 DFT⁺, N≥8 **no DFT under any of 12 conventions** | none / none | **no** — 4/8 odd cells lack the conjugation (example ≡ Rosetta raw output, bit-for-bit = 08/09) | correctFft matches conj(DFT⁻) on all pow2; validate oracle diverges up to 240 (N=16) | conj(07) ≡ 09 bit-exact; 05∘07 ≠ Id **by spec** (= time-reversed conjugate, closed form verified) | pow2 only (both fns); N=3 silent, N=5/7 correctFft heap-OOB; validate oracle memory-safe but wrong | **A + B + C + D** |
| 08_fft_split_fft | forward DFT, complex → split re/im | text silent; example pins sign=−1, unnorm (max dev 3.56e-6 = rounding) | sign=−1, unnorm (both fns, unique) | none / none — agree | **yes** (16/16 cells; no 09-style typo) | pow2 exact (~1e-15); N=3: both fns identical wrong output | composes: ifft05∘fft08 = Id ≤ 5.7e-15; 08 ≡ 09 bit-exact | pow2 only; N=3/6 silent-wrong, N=5/7 correctFft heap-OOB, N=1 UB | D (+ B: domain unstated) |
| 09_fft_fft_out_of_place | forward DFT, out-of-place | text silent; example pins sign=−1, unnorm (7/8 cells) | sign=−1, unnorm (both fns) | none / none — agree | **partial** — one-cell digit typo `-2.42421`; example's own k=7 conjugate carries the correct digits | pow2 exact on all classes; N∈{3,5,6,7} wrong/UB per fn | composes: with 05 to Id ≤ 5.3e-15 | pow2 only; N=3/6 silent, N=5/7/31 correctFft heap-OOB, N=1 UB | **A** (typo) + D + B |

Classification legend: A example wrong · B text wrong/ambiguous · C oracle wrong · D oracle valid only for restricted N · E legitimate alternative convention · F no problem.

Notable: **no deviation in the family is class E.** Wherever prompt and oracle disagree, the disagreement is not two defensible conventions side by side — it is a wrong example (06, 07, 09), a wrong oracle (07's validate path), or an undocumented domain restriction (05, 07, 08, 09).

## Recommendation for E4 (benchmark 06) — exactly one

**A) Keep the oracle, fix the prompt example (and state the convention in one sentence).**

Concretely (not implemented here): in the worked example, swap the imaginary signs of the two affected cells — `-8-12i` → `-8+12i` at k=1 and `-8+12i` → `-8-12i` at k=3 — in all three thesis prompt entries and the mirrored comment in `baseline.hpp`/`cpu.cc`; add one disambiguating sentence à la "using the convention X[k] = Σ x[n]·e^{−2πikn/N} (negative exponent, unnormalized)".

Justification along the five required axes:

1. **Family-internal consistency:** the oracle's convention (sign=−1, unnormalized) is the one 08 and 09 already implement bit-identically and 05 exactly inverts; the executed roundtrip `ifft05(dft06(x)) = x` holds at ≤ 8.8e-15. Changing the oracle to match the example (option B) would make 06 the only positive-exponent forward transform in the family, break the verified composition with 05, and diverge from the NumPy/FFTW/engineering standard the rest of the ecosystem assumes.
2. **Least change to the task:** the fix touches two example cells' imaginary signs plus one added sentence. The task semantics ("compute the DFT of a real vector") is unchanged; every correctly-implemented negative-exponent DFT that today fails the example-faithful reading becomes consistent.
3. **Deviation from upstream ParEval:** yes — deliberate and documented, exactly like the already-decided stencil/50 prompt fix. The upstream example is wrong (inherited from commit `05af9f8`); byte-compatibility with a wrong example is not worth preserving. Score comparability with upstream is unaffected by the *example* text; it would be destroyed by an *oracle* change (option B).
4. **Enhanced specs:** no regeneration forced. The enhanced tests grade differentially against the baseline, which does not change under A; 06's specs (8 cached + statics/mutations) remain valid. (Under option B, all 06 spec verdict-histories and the sha-pinned cache would be invalidated.) One caveat: any future spec derived from the *documented example's expected values* must be written against the corrected example.
5. **Roundtrip compatibility:** A preserves the only configuration in which the family composes to the identity (verified §Roundtrip); B would break `ifft05∘dft06 = Id` unless 05 were changed too, cascading into the whole family.

Option C (exclude 06) is unnecessary — the oracle is mathematically clean over the **full** N domain (the only family member without the radix-2 restriction), and one two-cell example fix makes the benchmark sound. Option D does not apply: no evidence is missing; the convention question is settled by execution and composition.

## Recommendations for the other four (list only — nothing implemented)

- **05:** example and oracle are consistent — no example fix. Address the domain: either state "N is a power of two" in the prompt or restrict enhanced spec sizes for the radix-2 family to powers of two (and drop/regenerate the two silent N=3 specs). Fix the N=1 shift-by-32 UB when the family is touched (one-line guard). The (·, extreme_values) ±DBL_MAX specs for fft benchmarks measure overflow lottery, not correctness — gate or drop them.
- **07:** the most defective family member; three coordinated repairs are needed before its numbers mean anything: (i) fix `fftCooleyTookey` to conjugate once at the end (or make validate() use `correctFft`) — class C oracle bug; (ii) conjugate the example's odd cells so it matches the text's "FFT then conjugate"; (iii) same domain handling as 05. Until then 07 contributes no valid enhanced signal (8/20 specs discarded, remainder graded against a non-DFT) and its ParEval verdicts are suspect for any input where conj matters.
- **08:** no example fix needed. Domain handling as 05; note the two-implementation gate is blind at N=3 (identical garbage from both baselines) — the spec-size restriction is the effective fix.
- **09:** fix the one-cell example typo (`-2.42421` → `-2.41421`) in the prompt entries and the mirrored driver comments. Domain handling as 05.
- **Family-wide:** the power-of-two restriction should be decided once for all radix-2 members (05, 07, 08, 09) — either prompt-documented restriction or spec-size filtering; 06 needs neither.

## Briefing premises that did not survive (per §7)

1. **"07's example has transposed real/imaginary parts at four odd positions" — refuted as a mechanism.** The example is the exact *unconjugated* DFT⁻ (token-identical to the Rosetta kernel output; no component was ever transposed). The "transposition" is an emergent artifact of comparing it against 07's (itself broken) validate oracle, and even there the literal re/im swap occurs only at k=3 and k=7 (at k=1 and k=5 the relation is ∓i·conj — magnitudes swap *and* both signs flip; verification V3's correction). The right description is: **the example is missing the conjugation the spec text demands.**
2. **"06's example corresponds to a positive-exponent DFT" — confirmed but under-determined.** On real input, DFT⁺ ≡ conj(DFT⁻) ≡ unnormalized IDFT are the *same vector*; the example pins the mismatch with the oracle, but not which of the three readings produced it. (For E4 this changes nothing — all three readings require the same two-cell fix.)
3. **The benchmark name list in §1 was correct this time** (verified against `drivers/cpp/benchmarks/fft/` before use), despite the briefing's own warning.
4. **"Heap corruption at N=5/7" needs a nuance:** the OOB write is ASan-proven, but whether it *manifests* as an abort (SIGABRT "malloc(): corrupted top size") or completes silently with corrupted heap is allocation-layout-dependent — both were observed across probe layouts (V2's correction). "Crash" is therefore not a stable classification; "out-of-bounds heap write, UB" is.
5. **Phase 0's pilot attribution for fft/05 was incomplete** (the briefing presented it as settled): the frozen 3-fail signature needs *two* mechanisms — the N=3 size-domain hole (2 fails) plus a distinct ±DBL_MAX/NaN-comparison artifact at in-domain N=4 (1 fail). Reconciliation is now full, verdict-for-verdict, from binary re-runs.
6. **The briefing's framing "the radix-2 baselines seem problematic for non-powers-of-two" understated one member and overstated another:** 06 is not radix-2 and is correct for all N; and beyond N∈{3,5,7}, N=6 is silently wrong and N=31 is also an OOB write.

## Beyond the ask / deliberately skipped

**Beyond the ask:** the 07 validate-oracle bug (class C — not in the briefing's context block at all) including its measured consequence of discarding 8/20 enhanced specs; the N=1 shift-by-32 UB across the Rosetta-derived baselines; N=6/N=31 domain probes; the (4, extreme_values) NaN-lottery mechanism with binary-level pilot re-runs (15/15 verdicts reproduced); token-level provenance including signed-zero matching; the gate replica reproducing the frozen `spec_gate_report.jsonl` 100/100; the reward-inversion receipt (the only two mathematically-correct general-N IDFT implementations in the pilot are the only "fail"s on the silent specs).

**Deliberately skipped:** gpu.cu/kokkos.cc variants (not exercised by the thesis pipeline); no fix drafting beyond the classification (per the brief); no re-scoring of pilot numbers (Phase 0's corrected-numbers document already excludes the affected figures); the omp/mpi *driver* paths beyond what the pilot reconciliation required (the baselines under audit are serial by construction); no browsing for the Rosetta page (the provenance proof is the in-repo citation at `05/baseline.hpp:11` plus token-exact reproduction by execution).

---

*Report produced by the Phase-0 follow-up FFT audit (2026-08-22): 12 agents (5 benchmark audits, roundtrip, specs, pilot reconciliation, common cause; 3 adversarial verifications, all CONFIRMED). Scratch scripts, probe binaries, and raw outputs: session scratchpad `fft_audit/*` — referenced throughout, not part of the repo.*

---

## Status as of Domain Approval Wave — 2026-08-25 — based on fb40fc893d347feb6df62e05b019a5577067fa79

Append-only status section; the text above is historical evidence and is unchanged.

- **Confirmed:** the family recommendation stands (05/07/08/09 power-of-two only; 06 any valid N, forward DFT, negative exponent, unnormalized — frozen invariant I12). The 07 top-level conjugation oracle defect remains queued for exactly one later fix; nothing was implemented in this wave.
- **New domain decision (D6b representability, this wave):** 07's MEDIUM was reduced 65536 -> 32768 (2^15). Mechanism: a naive direct-DFT spelling with an `int` twiddle index `n*k` is signed-overflow UB above N = 46341 (65535^2 = 4.295e9 ≈ 2x INT_MAX; the first wrap fires at n = k = 32769, producing a negative `(n*k)%N` index), and at N = 65536 the O(N^2) path can COMPLETE inside the 60 s run timeout — so the failure would be representability-caused, not a clean timeout. At 32768: 32767^2 = 1.0737e9 < INT_MAX. LARGE = 2^22 is kept: the naive path is runtime-dead there (1.76e13 iterations) and every N log N path is safe (indices < 2^22, magnitudes <= N·sqrt(2)).
- **Still open:** 07 oracle conjugation fix (oracle wave); prompt power-of-two statements (prompt wave).
