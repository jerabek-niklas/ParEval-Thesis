# Cross-Pilot Reevaluation after the Final Enhanced Freeze

pilot_001 vs. a prospective pilot_002, re-derived from local evidence after
Waves 1/1b/2A/2B/3 and Enhanced E1–E3.1.1.

The question this wave answers is **not** "did a file change?" but "can a
pilot_001 measurement be methodically compared with a measurement taken under
today's experiment semantics?". Both directions of the naive answer are wrong
here, and this wave has a concrete counterexample for each:

* `thesis/assembly/` and `thesis/generation/` changed **zero bytes** since
  pilot_001 — comparable, and provably so.
* `search/35`'s `cpu.cc` **did** change — and stays comparable at the
  correctness stage, because the added guard cannot fire there.
* `graph/15` and `reduce/25` have the **same `spec_key`s** in the enhanced
  suite — and only those two are same-input comparable, because they are the
  only pilot benchmarks with no fill site at all.

---

## 1. Provenance

| Item | Value |
|---|---|
| Repository | `jerabek-niklas/ParEval-Thesis` |
| Branch | `thesis-static-analysis` |
| Start HEAD | `6fc8a1a9a33d287f5dc7c87bf5f3502dfda9b859` (verified, not assumed) |
| Parent | `137695e62d94852ee970603274733f12604ef461` (E3.1.1) |
| Working tree at start | clean |
| Working tree at end | 3 modified/new files (§21) |
| pilot_001 baseline commit | `6846d689fd81186b2161786dc7f52d485ccf2b5c` (from the pilot_001 run manifest; `git_dirty == false`; verified ancestor of HEAD) |
| Superseded gate state | `5b22343b8b01456ee37b6a009ee26aba5c07a2e9` (Wave-3 cleanup) |
| Cross-Pilot checker before | **STALE**, exit 1 |
| Cross-Pilot checker after | **CURRENT**, exit 0 — and still not "pilot ready" (§22) |

`core.autocrlf = true` in this checkout. A first pass that hashed raw working-tree
bytes against `git show` blobs reported *every* file as changed. Every
change statement in this report is therefore produced by git-native comparison
(`git diff --name-status` / `--stat`), which is line-ending safe, and the method
was validated with a positive control on a file known to have changed.

---

## 2. pilot_001 evidence inventory (local records are authoritative)

Source: `thesis/results/intermediate/pilot_001/<model>/correctness.jsonl`,
base run only. The repair populations (`pilot_001__{static,test,combined}_feedback__iter{1,2}`,
715 further records) are a different population and are **not** mixed in.

| Item | Measured |
|---|---|
| Correctness records | **396** |
| Schema | `correctness.v1` (396/396) |
| `run_id` | `pilot_001` (396/396) |
| Benchmarks | **12** |
| Models | **11** |
| Execution models | **3** (serial, omp, mpi) |
| Sample ids | 1 (`sample_0`) |
| Expected cells (12 × 11 × 3 × 1) | 396 |
| **Missing cells** | **0** |
| **Duplicate cells** | **0** |

Verdicts: `pass` 315, `validation_failed` 66, `build_failed` 11,
`runtime_error` 3, `timeout` 1.

The 12 benchmarks: `dense_la/00`, `fft/05`, `geometry/10`, `graph/15`,
`histogram/20`, `reduce/25`, `scan/30`, `search/35`, `sort/40`, `sparse_la/45`,
`stencil/50`, `transform/55`.

The expected historical figure of 396 is therefore **reproduced from the actual
result files**, not adopted.

Enhanced records: **7920** (11 models × 720; 720 = 12 benchmarks × 3 execution
models × 20 specs). Statuses: `pass` 6676, `fail` 461,
`baseline_incompatible` 264, `build_failed` 206, `crash` 135,
`numerically_unstable` 132, `timeout` 46.

---

## 3. Historical Cross-Pilot baseline (the point to be reproduced)

| Field | Stored value |
|---|---|
| Classification | `PILOT_SUBSET_ONLY_QUANTITATIVE_COMPARISON_DEFENSIBLE_WITH_EXCLUSIONS` |
| Population | 396 cells |
| Retained candidate subset | `graph/15`, `reduce/25`, `search/35` — 99 cells |
| Excluded / unresolved | `dense_la/00`, `scan/30`, `transform/55` — 99 cells |
| Remainder (method-changed) | 6 benchmarks — 198 cells |
| Transport effect | 99 preserving / 0 changed / 99 unresolved |
| Change classes | K1–K7 (2 transport-only, 5 verdict-relevant) |
| Reuse | UNDECIDED |
| Invocation | `INVOCATION_SELF_DECLARED = true`, `PREFLIGHT_IS_DECLARATION_CHECK_NOT_ENFORCEMENT = true` |
| Environment | expected g++ 13.3.0 / Open MPI 4.1.6; container `TAG_ONLY` |
| Statistical caveats | 6 entries |

These counts were treated as the target to reproduce, not as input.

---

## 4. Prompt changes — reproduced from primary evidence

Byte diff of `thesis/prompts/generation-prompts-thesis.json` between the
pilot_001 commit and HEAD:

| Metric | Measured | Historical figure |
|---|---|---|
| Prompt entries changed | **69** / 180 | 69 |
| Benchmarks changed | **23** / 60 | 23 |
| Non-atomic changes (not all 3 execution models) | **0** | 0 |
| Pilot benchmarks affected | **4** | 4 |
| Pilot cells affected | **132** | 132 |

The four: `fft/05`, `geometry/10`, `sparse_la/45`, `stencil/50`.

Atomicity holds: every changed benchmark changed all three execution-model
prompts. No `serial` P1 is ever compared against an `omp` P2 within one
benchmark contract.

---

## 5. Benchmark / methodology changes

Git-native diff of the 12 pilot benchmark directories against the pilot_001
commit — **7** of 12 have changed sources:

| Benchmark | `cpu.cc` | `baseline.hpp` | Prompt |
|---|---|---|---|
| `dense_la/00` | — | — | — |
| `fft/05` | changed | changed | changed |
| `geometry/10` | changed | changed | changed |
| `graph/15` | — | — | — |
| `histogram/20` | changed | — | — |
| `reduce/25` | — | — | — |
| `scan/30` | — | — | — |
| `search/35` | changed | — | — |
| `sort/40` | changed | — | — |
| `sparse_la/45` | changed | — | changed |
| `stencil/50` | changed | changed | changed |
| `transform/55` | — | — | — |

The canonical benchmark-level change ledger (Wave-3 §9.12/§9.13,
A∪B∪C∪D∪E ∩ pilot) names **6**: `fft/05`, `geometry/10`, `histogram/20`,
`sort/40`, `sparse_la/45`, `stencil/50`. `search/35` is the seventh changed
file and is classified class-preserving (F). Both statements were re-checked
against the actual diff:

* **`search/35`** adds `if (TEST_SIZE == 0) { mismatchNoteNonFiniteReference(); return true; }`.
  At the correctness stage `TEST_SIZE = ENHANCED_TEST_SIZE_DEFAULT(1024)` with no
  enhanced override, so the guard is unreachable. Class-preserving confirmed.
* **`histogram/20`** adds an out-of-`[0,255]` domain guard. At the correctness
  stage `ENHANCED_FILL(image, 0, 255)` degenerates to `fillRand(image, 0, 255)`,
  so the guard is likewise unreachable — see §8 for why it nevertheless stays
  excluded.

---

## 6. K1–K7 reachability, measured on the actual records

Reachability was evaluated per case, not asserted from "code changed". No
pilot_001 stdout was re-parsed with the authenticated nonce parser and no
historical verdict was recomputed; stdout was read only as historical raw data.

| Class | Kind | Reachability | Evidence |
|---|---|---|---|
| **K1** nonce transport | TRANSPORT_ONLY | **NOT_REACHABLE** | 1144 run entries: exactly 1 `Validation:` line in each of the 1129 runs with output, 0 in the other 15. No run carries a second, candidate-emitted marker, so no historical verdict can have rested on a self-declared line. |
| **K2** non-finite reference → BI | VERDICT_RELEVANT | benchmark-dependent | Oracle-side reachable only for `dense_la/00` (unguarded pivot division, `baseline.hpp:17`). `scan/30` sums 2048 values in [-100,100]; `transform/55` is `max(0.0, v)` — neither can create a non-finite reference. Discrete payloads: impossible. |
| **K3** size mismatch → FAIL | VERDICT_RELEVANT | **NOT_REACHABLE** for the retained subset | The retained graded payloads are scalars; no container enters the graded path, so the new `fequal` size check cannot fire. |
| **K4** non-finite candidate → FAIL | VERDICT_RELEVANT | **NOT_REACHABLE** for the retained subset | `mismatchIsFinite()` is an `if constexpr` returning `true` for integral/boolean types, so both non-finite branches of `reportAndCompareScalarImpl` are compile-time dead for `int`/`bool`/`size_t`. |
| **K5** BI outranks process state | VERDICT_RELEVANT | **NOT_REACHABLE** | **0** occurrences of `BASELINE_INCOMPAT*` in the entire pilot_001 correctness stdout corpus. |
| **K6** repair terminal status | VERDICT_RELEVANT | **OUT_OF_POPULATION** | Repair vocabulary, outside the 396 iteration-0 cells. |
| **K7** legacy parser robustness | TRANSPORT_ONLY | **NOT_REACHABLE** | `driver_wrapper.py` is not part of this pipeline's productive path; no file of that name exists in the tree. |

### Non-finite records — a scope discrepancy, resolved

The stored artifact cites Wave-1 §8.4 for "4 correctness records with
non-finite `got=` values". Measured here on the **base run**: **2**
(`dense_la/00 × deepseek_v4_flash × mpi`, `sparse_la/45 × qwen36_35b_a3b × mpi`),
both already `validation_failed`, neither in the retained subset.

Extending the same scan across all `pilot_001*` runs gives base 2 +
`static_feedback__iter1` 1 + `static_feedback__iter2` 1 = **4**. The Wave-1
figure spans the repair iterations too. Different scope, not a contradiction —
and the 396-cell cross-pilot population contains 2. Both figures agree on the
substantive point: every visible non-finite case sits in an already-failing cell.

### K5 has a stage boundary worth naming

`baseline_incompatible` appears **0** times in pilot_001 correctness stdout but
**264** times in pilot_001 *enhanced* records. The BI vocabulary existed in the
enhanced stage at pilot_001 time (via the baseline gate) and not in the
correctness stage. The artifact's "pilot_001 predates the BI vocabulary" claim
is correct **as scoped to the correctness records** and should not be read
suite-wide.

---

## 7. Semantic interlocks — made visible, not solved

Seven interlocks remain `disclosure_required` /
`BLOCKED_PENDING_SEMANTIC_DECISION` (`prompt_oracle_interlock.json`):
`dense_la/00`, `geometry/12`, `geometry/13`, `geometry/14`, `histogram/22`,
`scan/34`, `search/37`.

Exactly **one** — `dense_la/00` (BL-01) — is inside the pilot population,
covering **33** cells. The other six are outside the 12 pilot benchmarks.

Nothing was resolved here: no automatic exclusion, no verdict override, no
tie-break invention, no tolerance invention. The interlock is now a first-class
per-cell class so the ambiguity cannot be lost in an aggregate.

---

## 8. Correctness cell matrix

| Class | Cells | Benchmarks |
|---|---|---|
| `DIRECTLY_COMPARABLE` | **99** | `graph/15`, `reduce/25`, `search/35` |
| `SEMANTIC_INTERLOCK` | **33** | `dense_la/00` |
| `INSUFFICIENT_EVIDENCE` | **66** | `scan/30`, `transform/55` |
| `METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE` | **198** | `fft/05`, `geometry/10`, `histogram/20`, `sort/40`, `sparse_la/45`, `stencil/50` |
| **Total** | **396** | 12 |

Verdict distributions recomputed from the records:

| Class | Distribution |
|---|---|
| `DIRECTLY_COMPARABLE` | build_failed 2, pass 94, runtime_error 1, validation_failed 2 |
| `SEMANTIC_INTERLOCK` | pass 29, validation_failed 4 |
| `INSUFFICIENT_EVIDENCE` | build_failed 1, pass 63, timeout 1, validation_failed 1 |
| `METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE` | build_failed 8, pass 129, runtime_error 2, validation_failed 59 |

The retained distribution equals the stored `candidate_subset.verdict_distribution`
**exactly**, and `SEMANTIC_INTERLOCK` + `INSUFFICIENT_EVIDENCE` together equal the
stored `excluded_from_prior_198_cell_proposal.verdict_distribution` **exactly**
(build_failed 1, pass 92, timeout 1, validation_failed 5).

### Both conjuncts of the selection rule re-verified against current source

1. **Not in the benchmark-level change ledger** — reproduced in §5.
2. **Exclusively discrete graded payload** — read from today's `cpu.cc`:
   `graph/15` grades `int`, `reduce/25` grades `bool`, `search/35` grades
   `size_t`; `dense_la/00`, `scan/30`, `transform/55` all grade
   `std::vector<double>`.

### `histogram/20`: an honest note, not a silent widening

`histogram/20` has byte-identical prompts and its only source change is an
enhanced-stage-only domain guard, so its correctness cells are arguably
unaffected. It **remains excluded** because the selection rule keys on the
frozen benchmark-level ledger (§34 category B), and widening the comparable
population is a decision this comparability wave is not authorised to make.
Recorded in the artifact as a candidate for a future, explicit decision.

---

## 9. Correctness quantitative subset

**99 of 396 cells** are directly quantitatively comparable — unchanged.

The 99 comparable cells and the 99 cells requiring disclosure are **the same
99**: the project classification never admits them without the documented
disclosures (suite-wide transport note, 1-sample limit, selection bias,
BL-01 interlock context). There is no separate disclosure-only population, and
none was invented to fill the slot.

### Previous 99 / 99 / 198 structure: **unchanged**

Proven with current evidence, not assumed:

* the 396-cell population reproduces exactly from the local records;
* both stored verdict distributions reproduce exactly;
* both conjuncts of the selection rule reproduce from current source;
* every fingerprint that made the gate STALE is enhanced-side (§10, §16).

The only refinement is finer labelling *within* the unresolved 99 (66 +
33) so the open interlock is machine-visible. No cell moved between groups.

---

## 10. Normal correctness vs. Enhanced — strictly separated

`NORMAL_CORRECTNESS_INPUT_PATH_CHANGED = false`, confirmed source-based from the
committed state:

1. `fillRand()` in `drivers/cpp/utilities.hpp` is **byte-identical** to the
   pilot_001 version (function extracted from both revisions and hashed:
   `64ecbd3131d0…`).
2. Without the enhanced compile defines, `ENHANCED_FILL(x, lo, hi)` expands to
   `fillRand(x, lo, hi)` and `ENHANCED_TEST_SIZE_DEFAULT(d)` expands to `(d)`.
3. The correctness build (`build_config.py`) emits only the execution-model
   macro, `DRIVER_PROBLEM_SIZE` and diagnostic flags.
   `ENHANCED_FILL_PATTERN` / `ENHANCED_TEST_SIZE` / `ENHANCED_RUNTIME_FILL` are
   emitted **exclusively** by `run_enhanced_tests.py`.

All six items that made the gate STALE are enhanced-side: three
`enhanced_spec_keys_sha256` projections plus `enhanced-fill.hpp`, `specs.py`
and `run_enhanced_tests.py`. Not one correctness-relevant fingerprint moved.
Enhanced work therefore does not invalidate normal-correctness comparability.

---

## 11. pilot_001 Enhanced evidence

Historical spec identities are taken from the spec objects **stored inside the
result records**, never from a reconstruction.

| Item | Measured |
|---|---|
| Records | 7920 |
| Benchmarks | 12 |
| Models / execution models / sample ids | 11 / 3 / 1 |
| Distinct executed `spec_key`s | **240** (exactly 20 per benchmark) |
| Summary provenance | `enhanced_execution_provenance`, `enhanced_model_execution_provenance`, `enhanced_policy_provenance`, policy hash, specs hash: **all absent** |

Historical pattern distribution over the 240 distinct keys: `random` 79,
`extreme_values` **35**, `explicit_values` 34, `all_zeros` 23, `all_same` 22,
`ascending` 15, `alternating` 12, `duplicate_at` 8, `descending` 6,
`sorted_except_one` 6.

The pilot_001 manifest records the seed cache as
`sha256 = 0fe9561e1350…`, 483 specs — **byte-identical to the versioned pre-E3
snapshot** `thesis/enhanced_tests/frozen/e3_pre_specs.jsonl`. The historical
seed state is thus fully preserved; what is missing is the harness fingerprint.

---

## 12. Current frozen Enhanced suite

`frozen/e3_final_specs.jsonl` (`49b0229c…`, 471 unique valid seed specs)
materialized through today's `build_benchmark_specs`, no execution:

| Item | Value |
|---|---|
| Productive specs | **1200** |
| Per benchmark | **20** (all 60) |
| Distinct productive `spec_key`s | **1200** |
| `extreme_values` | **0** |

Patterns: `random` 549, `explicit_values` 169, `all_same` 131, `all_zeros` 77,
`ascending` 69, `alternating` 64, `duplicate_at` 50, `spike_at` 41,
`descending` 31, `sorted_except_one` 19. Sources: static 219, llm 433,
mutation 548. Sizes span 0…4096.

---

## 13. Old / current Enhanced key overlap

Per pilot benchmark, historical executed keys vs. current productive keys:

| Benchmark | old | new | SAME | OLD_ONLY | NEW_ONLY |
|---|---|---|---|---|---|
| `dense_la/00` | 20 | 20 | 12 | 8 | 8 |
| `fft/05` | 20 | 20 | 11 | 9 | 9 |
| `geometry/10` | 20 | 20 | 12 | 8 | 8 |
| `graph/15` | 20 | 20 | 5 | 15 | 15 |
| `histogram/20` | 20 | 20 | 15 | 5 | 5 |
| `reduce/25` | 20 | 20 | 11 | 9 | 9 |
| `scan/30` | 20 | 20 | 10 | 10 | 10 |
| `search/35` | 20 | 20 | 12 | 8 | 8 |
| `sort/40` | 20 | 20 | 13 | 7 | 7 |
| `sparse_la/45` | 20 | 20 | 8 | 12 | 12 |
| `stencil/50` | 20 | 20 | 17 | 3 | 3 |
| `transform/55` | 20 | 20 | 13 | 7 | 7 |
| **Total** | **240** | **240** | **139** | **101** | **101** |

All **35** historical `extreme_values` keys are `OLD_ONLY`.

---

## 14. Enhanced input drift, and the mutation-frontier caveat

Drift was determined with the productive, test-frozen classifier
`classify_specs_e2b.drift_reason` (E2-A DType map + E2-B spike/extreme
semantics) — not a new rule invented here.

**`SAME_KEY_DRIFTED` in the pilot population = 0.** Because:

* no pilot benchmark appears in the E2-A DType drift map (it covers
  `reduce/28`, `scan/31`, `sort/42`, `sort/43`);
* no `SAME_KEY` spec uses `spike_at` — all 3 current `spike_at` specs are
  current-only.

**`extreme_values` is not reinterpreted.** `pattern` is part of `spec_key`, so a
historical `extreme_values` spec can never match a current `alternating` spec;
all 35 are structurally `OLD_ONLY`. The E2-B finding that both now realize the
same bytes does **not** make the historical results reusable — that run executed
the *old* extreme semantics.

**E3 re-execution set.** The 10 authoritative retained-drifted specs (same
`spec_key`, changed input semantics) touch 9 benchmarks — `dense_la/03`,
`geometry/11`, `scan/31` (×2), `search/36`, `search/39`, `sort/42`,
`sparse_la/46`, `sparse_la/47`, `sparse_la/48`. **None is in the pilot_001
population**, so they contribute 0 here and remain non-comparable wherever they
do apply.

**Mutation-frontier caveat.** The pilot_001 productive suite was never just the
seed rows: `build_benchmark_specs` combined static base + LLM seeds + mutations,
and the historical frontier was additionally shaped by duplicate and invalid
seed rows (E3.1). Today's frontier is built from unique valid artifact seed
identities. That is precisely why the historical side of this comparison comes
from the **result records** and is never reconstructed by running today's
mutator over the old seed file.

**Residual dependency, stated plainly.** For the 9 pilot benchmarks that *do*
have a fill site, "same input" additionally rests on the E2-A.1 measurement that
the rewritten `enhanced-fill.hpp` is value-identical to the old header for every
range the validator admits. That was not re-measured here. It is not
load-bearing: all 123 of those `SAME_KEY` specs are already excluded from direct
comparability on verdict-mechanism grounds (§15).

---

## 15. Enhanced comparability matrix

Identical key **and** identical input is not sufficient — the oracle/verdict
mechanism must also be unchanged for that case.

| Class | Spec keys |
|---|---|
| `SAME_KEY` | 139 |
| `SAME_KEY_SAME_INPUT` | 139 |
| `SAME_KEY_DRIFTED` | 0 |
| **`DIRECT_SAME_INPUT_COMPARABLE`** | **16** |
| `SAME_KEY_SAME_INPUT_VERDICT_MECHANISM_CHANGED` | 123 |
| `HISTORICAL_ONLY_SPEC` | 101 |
| `CURRENT_ONLY_SPEC` | 101 |

Only **`graph/15` (5)** and **`reduce/25` (11)** qualify as direct same-input
comparable, and the argument is structural:

* both have **zero `ENHANCED_FILL` sites** (`pattern_effect: NONE` in the
  capability catalog), so neither the E2-A.1 fill rewrite nor any E2-B pattern
  policy can reach their input — it varies through `size` alone;
* `rand()` is deliberately unseeded (`utilities.hpp:251`, "as if `srand(1)`"),
  so their inputs are byte-reproducible;
* their `cpu.cc` and `baseline.hpp` are byte-unchanged since pilot_001;
* their graded payloads are discrete scalars, so the K2/K4 additions in
  `reportAndCompareScalarImpl` are compile-time dead.

`sparse_la/45` also has no fill site but its `cpu.cc` changed substantially, so
its verdict mechanism changed.

`INSUFFICIENT_HISTORICAL_PROVENANCE` applies to the enhanced stage as a whole,
not per spec: pilot_001 enhanced summaries carry no policy hash, no specs hash
and no execution fingerprint. The harness state is pinned only indirectly via
the run manifest's `git_commit`, which the **generation** stage wrote on
2026-08-12 while the enhanced stage ran on 2026-08-20. This stays
`HISTORICAL_PROVENANCE_LIMITATION`. The E3.1.1 execution and model fingerprints
describe the **current** condition only and are not retroactively attributed to
pilot_001.

---

## 16. Generation / assembly comparability

**`DIRECTLY_COMPARABLE`.** `git diff --name-status` between the pilot_001 commit
and HEAD over `thesis/assembly/` and `thesis/generation/` is **empty** — 13
tracked files, zero changed. Verified with a positive control
(`thesis/enhanced_tests/specs.py` → `M`) so the empty result is not a path typo.
The generation *condition* hash is independently unchanged (`e22ce9be…`).

Only fingerprint code was extended since the last cross-pilot freeze; productive
assembly semantics did not move. Classified accordingly — a changed file is not
automatically a changed semantics, and an unchanged file is not automatically
proof of one.

Separate axis, reported separately: the generation **input** did change — the
prompt text of 4 of 12 pilot benchmarks (§4).

---

## 17. Environment / toolchain — **UNKNOWN**

| Source | Value |
|---|---|
| Expected | g++ 13.3.0, `mpirun (Open MPI) 4.1.6` |
| pilot_001 `run_manifest.json` → `primary_compiler_version` | **`null`** |
| pilot_001 `run_manifest.json` → `toolchain_versions` | **`null`** |
| pilot_001 `toolchain-versions.txt` | g++ 13.3.0, `mpirun (Open MPI) 4.1.6` — **match** |

The recorded *versions* match. What is not proven is that they were in force
**during the run**: `toolchain-versions.txt` is stamped 2026-07-31 (image build
time) while correctness ran 2026-08-13 and enhanced 2026-08-20, and the
container is `TAG_ONLY` pinned, so a rebuild can drift silently. The run
manifest, the one artifact that would bind versions to the run, holds `null`.

Nothing was invented to fill that hole. Classification: **UNKNOWN** at run
level, with matching artifact values recorded as supporting — not conclusive —
evidence. `ENVIRONMENT_RUNTIME_CHECK = REQUIRED` stands. This is kept strictly
apart from methodical benchmark comparability.

---

## 18. Invocation

`INVOCATION_SELF_DECLARED = true` and
`PREFLIGHT_IS_DECLARATION_CHECK_NOT_ENFORCEMENT = true` are **unchanged** —
current source gives no reason to alter either.

`run_correctness.py` still exposes exactly the six CLI dimensions the policy
covers (`--config`, `--profile`, `--model-id`, `--primary-compiler`,
`--run-timeout`, `--run-id`), mapping onto the seven declared invocation fields.
The frozen expected values remain reproducible from productive defaults
(`primary_compiler = g++`, `run_timeout_seconds = 120.0`).

One documented gap narrowed: E3.1.1 now persists the **effective**
`run_timeout_seconds` and effective jobs map inside the enhanced execution
fingerprint (component G). "The effective `--run-timeout` is persisted nowhere"
is therefore closed for the **enhanced** stage and remains open for
`run_correctness.py`.

---

## 19. Static / repair

**`STATIC_REPAIR_COMPARABILITY = NOT_REEVALUATED_IN_THIS_WAVE`.**

Wave-2B §35 item D ("STATIC/REPAIR WAVE: GCC analyzer event path, tool-state
model, PARCOACH, LLOV gate, retry semantics") is still queued and explicitly
untouched. This area is **not** implicitly marked current or comparable; a
dedicated wave is required before any static or repair result is compared
across pilots.

---

## 20. Statistical limitations (retained in full)

All six caveats stay in the artifact verbatim. Formal comparability is not
statistical strength:

* exactly 1 sample per cell — no within-cell variance estimation;
* only 12 of 60 benchmarks in pilot_001, and only 3 of those 12 remain
  quantitatively comparable;
* the retained subset is exclusively scalar discrete-output benchmarks — a
  structural selection toward the simplest output class, not generalizable;
* double selection bias: stratified 12-benchmark pilot, then method-stability
  filtering;
* reuse UNDECIDED, so generation-vs-grading attribution sharpness is open;
* the classification asserts formal admissibility on the named 99 cells only.

Correctness cells and enhanced spec keys are never merged into one percentage —
different populations, different units.

---

## 21. Updated fingerprints

| Item | Value |
|---|---|
| Old cross-pilot fingerprint | `2d99753f4e9e4c84ecc3d71ec76f8ec30926dc4b9ffc558639f861d9588cb563` |
| New cross-pilot fingerprint | `3469f4a9f7d1de31c819343bc048ebf2842237edd4a7a5e8669d900a83bd15c1` |
| Rule | `canon_sha256` of the parsed file content with the two fingerprint fields removed — the checker's own helper |

Every stored state fingerprint was recomputed by calling the checker's own
functions (`recompute_state`, `sha256_file_bytes`,
`generation_condition_projection`, `evaluation_condition_projection`,
`assembly_condition_projection`, `canon_sha256`). No hash was written by hand.

The self-fingerprint is computed over the **on-disk** form. A first attempt
hashed the in-memory structure and did not reproduce when read back: the
enhanced size distribution has integer keys, which JSON turns into strings. The
value is now taken after a serialize/reload round-trip, so anyone can reproduce
it from the file alone — load the JSON, delete the two fingerprint fields,
`canon_sha256` the rest.

`check_cross_pilot_gate.py` now verifies that self-fingerprint on every run and
returns `UNRESOLVED` (exit 2) when the artifact was edited without recomputation.
Confirmed by a negative control: injecting a hand-edited `classification` value
produced `MISMATCH … CROSS_PILOT_GATE_STALE = UNRESOLVED`, exit 2, and the
artifact was restored byte-for-byte afterwards.

Changed files: `thesis/evaluation/cross_pilot_comparability.json` (M),
`thesis/evaluation/check_cross_pilot_gate.py` (M), this report (new).

### One deliberate rule change, provably neutral

The benchmark-local enhanced-spec projection previously read
`thesis/results/cache/enhanced/specs.jsonl` — which `.gitignore:23` ignores, so
it is not reproducible in a fresh clone. It now reads the version-controlled
`thesis/enhanced_tests/frozen/e3_final_specs.jsonl`, with the cache kept as a
fallback. Both files were verified **byte-identical** (`49b0229c…`, 471 specs),
and the recomputed hashes are unchanged before and after the switch
(`31f0c85a…`, `2a013371…`, `c3a1c9f4…`). This buys fresh-clone reproducibility
at zero numeric cost; the artifact's `hash_rule` text was updated to match.

---

## 22. External gates still open

The checker no longer blocks on `STALE CROSS-PILOT STATE`. It does **not**
report "pilot ready", and it should not:

* 7 semantic interlocks — `disclosure_required`, `BLOCKED_PENDING_SEMANTIC_DECISION`
* pilot_002 population — `NOT_YET_DECIDED`
* pilot_002 base run_id — `NOT_YET_CONFIGURED`
* reuse — `UNDECIDED`
* publication policy — unchanged
* static/repair comparability — `NOT_REEVALUATED_IN_THIS_WAVE`
* `EFFECTIVE_INVOCATION_RUNTIME_CHECK = REQUIRED` (pilot preflight)
* `ENVIRONMENT_RUNTIME_CHECK = REQUIRED` (container is `TAG_ONLY` pinned)
* post-run manifest verification — `REQUIRED_NOT_IMPLEMENTED`

---

## 23. Final classification

**`PILOT_SUBSET_ONLY_QUANTITATIVE_COMPARISON_DEFENSIBLE_WITH_EXCLUSIONS` —
unchanged.** Neither tightened nor loosened.

* **Correctness:** 99 of 396 cells directly quantitatively comparable, with
  mandatory disclosures. 198 method-changed, 66 insufficient evidence, 33
  semantic interlock.
* **Enhanced:** reported separately. 16 spec keys direct same-input comparable
  (`graph/15`, `reduce/25` only), 123 same-key-same-input but
  verdict-mechanism-changed, 101 historical-only, 101 current-only, 0 drifted.
  Largely **not** directly comparable.
* **Generation/assembly:** directly comparable (zero-byte diff).
* **Environment/toolchain:** UNKNOWN at run level.
* **Invocation:** policy unchanged, self-declared.
* **Static/repair:** not reevaluated.

Comparability is not reuse. This wave records which measurements *could* be
compared; it decides nothing about which will be.
