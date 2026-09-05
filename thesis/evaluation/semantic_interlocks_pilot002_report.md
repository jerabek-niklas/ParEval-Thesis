# Semantic Interlocks — Final pilot_002 Decisions, Atomic Prompt Clarifications & Disclosure Freeze

The seven prompt/oracle semantic interlocks left open by Wave 3 are now final:
six conventions are stated explicitly in the prompts, one tolerance regime is
deliberately accepted as a disclosure-bearing open convention. No oracle, no
comparator, no enhanced spec and no pilot_001 prompt changed.

Every decision was produced by an independent read-only audit per benchmark
(oracle executed empirically in the analysis container on the ambiguous input
class), then attacked by three adversarial reviewers with distinct lenses
(oracle empirics, methodology, enhanced/correctness impact) — 28 agents, 863
tool calls. All 18 reviewers of the six RESOLVED proposals returned "not
refuted, high confidence, 0 blocking findings". All three reviewers of the
`dense_la/00` proposal confirmed its status but refuted one of the audit's
empirical claims; that claim was withdrawn (§4).

---

## 1. Provenance

| Item | Value |
|---|---|
| Repository / branch | `jerabek-niklas/ParEval-Thesis` / `thesis-static-analysis` |
| Start HEAD | `068ac0b28ebb4b0d15f4392da1040cb7fd5f2735` (verified, not assumed); parent `6fc8a1a9…` (cross-pilot reevaluation) |
| Working tree at start | clean, no untracked files (`.claude/` not inspected) |
| End HEAD | unchanged — no commit |
| Gates before changes | `check_prompt_oracle_consistency.py` (container): `consistent=60`, exit 0; `check_cross_pilot_gate.py`: CURRENT, exit 0 |
| pilot_001 prompt baseline | commit `6846d689…` (all 21 prompts of the seven benchmarks were byte-identical to upstream ParEval before this wave) |
| Toolchain for empirics | container `pareval-thesis`, g++ 13.3.0, probes also under `-fsanitize=undefined,address` |

`core.autocrlf = true` in this checkout: the committed `generation-prompts-thesis.json` blob is LF, the working tree CRLF. All SHAs of that file below are quoted for the LF blob.

---

## 2. Starting state: 7 benchmarks / 21 prompt pairs

`prompt_oracle_interlock.json`: `interlock_benchmark_count = 7`,
`interlock_prompt_pair_count = 21`, `enforcement = disclosure_required`, every
entry `BLOCKED_PENDING_SEMANTIC_DECISION`.

| Benchmark | Registry id | Open question |
|---|---|---|
| `dense_la/00` | BL-01 | LU validated by absolute 1e-3 against one reference; attainable for other rounding orders? |
| `geometry/12` | BL-05 | degenerate triples; n < 3 |
| `geometry/13` | BL-06 | n < 2 (registry claimed a DBL_MAX sentinel) |
| `geometry/14` | BL-07 | n < 2 (same claim) |
| `histogram/22` | AXIS-CONVENTION-OPEN | points on an axis / origin |
| `scan/34` | BL-10, BL-11 | empty subarray admissible? size-0 result? |
| `search/37` | TIE-BREAK-OPEN | equally close to π |

Two facts about the starting state were found wrong during the audit and are
recorded in the registry's `_meta.semantic_wave_update.factual_corrections`:

* the registry's `oracle_behavior` for `geometry/13` and `geometry/14` ("DBL_MAX
  sentinel, implementation accident") — both oracles return **0** for n < 2
  through an explicit, commented, upstream-original guard; DBL_MAX is only the
  minimum initialiser and leaks solely for n ≥ 2 when no finite distance
  exists, which the E2-B domain makes unreachable;
* the decision-id cross-reference: in `thesis/docs/oracle-correctness-audit.md`
  BL-05 is `geometry/13`'s n<2 finding and BL-06 its overflow finding;
  `geometry/12` has no BL number there (decision-table row 124, bullets
  481–482). The registry/contract ids were kept as decision ids; the
  cross-reference is recorded per decision.

---

## 3. Decision principles

Priority, applied and cited per decision: (1) semantics already in the prompt,
(2) established mathematical/algorithmic definition, (3) worked examples,
(4) the input range actually produced, (5) existing oracle behaviour,
(6) minimal additional convention. "Oracle does X → X is the contract" was
never used as an argument; where several standard conventions exist and the
oracle stably implements one of them, that variant was written into the prompt
(implicit oracle convention → explicit benchmark contract), which introduces no
new grading semantics.

Preconditions were preferred over sentinels **only** where generator,
correctness and enhanced stages all respect them today. Where the
contract-preferred precondition would invalidate frozen E3 seeds, that path was
recorded as `precondition_path_blocked_by` (a
`BLOCKED_PENDING_ENHANCED_REGENERATION` path if ever pursued) and the
convention the oracle already implements was made explicit instead — visibly,
never silently.

Wording: every inserted sentence is the sentence the project's own domain table
(`thesis/docs/benchmark-domain-table.json`, `prompt_restriction_needed`) had
already queued, adopted verbatim; for `scan/34` the corpus idiom "Assume …"
(histogram/23) was used for the precondition.

Global invariants: general `fequal`, general tolerance, K1–K7 comparator
policy, non-finite policy, verdict schema, oracles, capability/policy catalog,
frozen E3 specs — all unchanged (§13–§15).

---

## 4. `dense_la/00` — BL-01 → ACCEPTED_DISCLOSURE_REQUIRED_FOR_PILOT_002

**What is and is not ambiguous.** The factorization convention is *not*
ambiguous: the worked example `[[4,3],[6,3]] → [[4,3],[1.5,-1.5]]` pins
Doolittle packing, unit L implicit, no pivoting (measured: Crout and partial
pivoting both fail the example), and that factorization is unique on the
produced domain. What is open is the floating-point tolerance regime.

**Reachability, measured.** On the thesis correctness stream
(`DRIVER_PROBLEM_SIZE = 1<<8`, not upstream's `1<<10`) validation trial 1 at
N=512 has max|LU| ≈ 3.8e5 and min pivot 0.062. A mathematically identical
Doolittle written as accumulate-then-subtract exceeds 1e-3 at 52 indices —
exactly the recorded pilot_001 `qwen3_coder_api` serial/omp FAIL, reproduced
bit-exactly at index 205201 (`expected=182070.86024185043`,
`got=182070.86173061817`, rel 8.2e-9). The rejected code's componentwise
backward error (1.8e-16) equals the oracle's (2.1e-16). Pure loop interchanges
(kij/kji/jki/ikj) are bit-identical; blocked, FMA-contracted and reciprocal
variants differ by 1e-4…3e-3 depending on the draw.

**Why no local resolution.** Levels 1–5 yield no tolerance: 1e-3 → 1e-2 and
absolute → relative are forbidden; a Higham-type backward-error residual is the
derivable level-2 contract (measured ≈ 2e-16 vs n·u = 5.7e-14) but is a new
grading methodology whose bound constant is itself a frozen-decision matter,
interacts with the frozen non-finite-reference gate on six singular enhanced
specs, and is a validator redesign for an oracle that is not wrong; a smaller
TEST_SIZE changes the graded input of a pilot_001 benchmark (margin continuous
in N: N ≤ 128 0/40 draws, N = 256 draw-dependent) and would force a full
cross-pilot reevaluation. The prompt is unambiguous and is **not** changed.

**Withdrawn after adversarial review.** The audit claimed the pipeline's own
enhanced-stage stability probe "flags the trial-1 matrix (38 indices over
1e-3)". All three reviewers refuted it independently: the real probe
(`baseline_selftest.build_probe_wrapper`, a single-TU oracle copy under
`optimize(O2,fast-math,fp-contract=fast)` + `target(x86-64-v3)`) run through
the real driver **passes both correctness matrices** (perturbation 6.25e-5 /
5.34e-4). The audit had compiled its input fill under `-ffast-math` too. The
claim, the level-5 "contradiction" argument and the "apply the gate to the
correctness stage" suggestion were removed from the decision text.

**Meaning of the status.** `dense_la/00` runs in pilot_002 unchanged; verdicts
are technically unchanged; no sample is excluded; this is a conscious
methodical acceptance, not a pending blocker. The registry entry now carries
`status = ACCEPTED_DISCLOSURE_REQUIRED_FOR_PILOT_002` and a machine-readable
`reporting_requirement` (§17).

---

## 5. `geometry/12` — BL-05 → RESOLVED

Oracle (`baseline.hpp:12–33`): n < 3 → 0; unfiltered minimum over all C(n,3)
triples, so a collinear or coincident triple contributes exactly 0. Measured:
n0=n1=n2=0, collinear → 0, duplicate → 0. The prompt itself supplies
`triangleArea()`, which returns 0 for degenerate input, and says "any 3 points"
without qualifier.

Decision: (a) degenerate triples count with area 0 — level 2 (shoelace /
signed-area definition), corroborated by level 1 (the supplied helper) and
level 5; (b) fewer than 3 points → 0 — level 5 + 6, because the
contract-preferred precondition "at least 3 points" would invalidate the
frozen seeds (2, all_zeros) and (1, all_zeros) and 12 productive keys (min_size
3 is not even expressible in the catalog), and a non-degeneracy precondition
would invalidate all 8 frozen seeds. The +∞ convention was considered and
rejected (requires an oracle change; a +∞ reference would make the seven n<3
productive specs vacuous). `geometry/11` is not a uniform-0 sibling (it returns
twice the segment length for two distinct points); 13 and 14 are. Corpus
precedent for stating degenerate returns: `geometry/11`, `reduce/28` (Wave 3).

Inserted after the first comment line, identical in serial/omp/mpi:

> Three collinear or coincident points count as a triangle of area 0, so the answer is 0 whenever any three of the given points are collinear or coincident.
> If fewer than 3 points are given, return 0.

Reach today: 17/20 productive specs hit the degenerate class; correctness
(n=1024, independent uniform doubles) never does.

---

## 6. `geometry/13` — BL-06 → RESOLVED

Oracle returns **0** for n < 2 (`baseline.hpp:13–15`; measured n0=0, n1=0;
real driver at `-DENHANCED_TEST_SIZE=1`: a candidate returning 0 passes, +∞ and
DBL_MAX fail). The registry's DBL_MAX claim was wrong.

Decision: fewer than two points → 0, level 6 after level 2 gave only the
precondition n ≥ 2, whose enforcement (`enforced_size_safety.min_size = 2`)
invalidates the frozen seed (1, all_zeros, llm) and 3 productive specs and
fails `verify_e3_frozen_artifacts.py` — simulated in-process, not applied.
Chosen on merit, not because the oracle does it: finite (comparator-compatible),
family-consistent (14 has the identical guard), upstream-neutral (upstream never
grades n<2), the audit document's own option (a). The preferred long-term
contract (precondition n ≥ 2 with min_size 2) is recorded as deferred to the
next enhanced regeneration wave. Size 0 stays DISALLOWED; the contract sentence
covers it while the suite tests only n = 1.

Inserted: **"If the vector contains fewer than two points, return 0."**

---

## 7. `geometry/14` — BL-07 → RESOLVED

Identical guard, identical situation (frozen seed (1, explicit_values [42.0]);
min_size 2 would reshuffle 5 productive specs). Decided consistently with 13.
BL-07's strongest objection — 0 is a legal distance, so "no pair" is
indistinguishable from "a coincident pair" — is answered explicitly: for a
grading contract the collision is irrelevant once the rule is stated (candidate
and oracle are compared on the same input); 0 is finite and therefore gradable
under the frozen non-finite policy; among finite candidates 0 is the upstream
oracle behaviour and the family idiom (12/13/14). The frozen seed is
oracle-derived (the seed LLM saw `baseline.hpp`) and is cited only to show that
size 1 cannot be excluded, never as merit.

Inserted: **"If the vector contains fewer than two elements, return 0."**

---

## 8. `histogram/22` — AXIS-CONVENTION-OPEN → RESOLVED

Exact oracle convention (`baseline.hpp:16–28`, measured):

| Point | bin |
|---|---|
| origin (0,0), also (−0.0,−0.0) | bins[0] |
| positive x-axis (x>0, y=0) | bins[0] |
| positive y-axis (x=0, y>0) | bins[0] |
| negative x-axis (x<0, y=0) | bins[1] |
| negative y-axis (x=0, y<0) | bins[3] |

Deterministic, total over finite doubles, sanitizer clean, upstream-inherited.
Reach: the correctness fill cannot produce an exact 0.0 (RAND_MAX = 2³¹−1,
exhaustive scan); the enhanced suite reaches the origin in 6/20 productive
specs, and a strict-inequality or zero-negative candidate fails exactly those 6.

Level 2 says axis points belong to no quadrant; adopting it needs an oracle
change (flips 6/20 verdicts, not a bug) or a precondition (invalidates frozen
seeds 2/4/6). The wave rule therefore selects level 5, the only non-blocking,
verdict-preserving resolution. Precedent: Wave 3 fixed `histogram/21`'s
boundary value 100 by a prompt sentence.

Inserted after "Store the counts in `bins`.":

> A point counts into bins[0] if x >= 0 and y >= 0, into bins[1] if x < 0 and y >= 0, into bins[2] if x < 0 and y < 0, and into bins[3] if x >= 0 and y < 0; points lying exactly on an axis or at the origin are therefore counted by these non-strict comparisons and are never dropped.

---

## 9. `scan/34` — BL-10 → RESOLVED (explicit algorithmic convention)

Oracle (`baseline.hpp:14–22`): `largestSum = INT_MIN`, only sums of non-empty
runs are assigned → **non-empty** convention. Measured: `[-3,-1,-7,-2] → -1`,
`[-5,-3] → -3`, example → 6. Level 2 narrows the space to the two standard
conventions (CLRS 4.1 / LeetCode 53 non-empty; Bentley/Kadane empty-allowed)
without selecting; level 3 does not discriminate; level 4: 6/20 productive
enhanced specs are all-negative (the correctness fill never separates the
conventions); level 5 selects per the wave's tie-break rule (the oracle is
stable and unchanged through upstream fix 883ed97). Seed rationales are
oracle-derived and were not counted as evidence. The minimal wording was chosen
deliberately — a corollary ("largest element for all-negative input") would
read as coaching.

Inserted: **"The subarray must be non-empty."**

## 10. `scan/34` — BL-11 → RESOLVED (input precondition)

Empty input returns the INT_MIN accumulator artefact. The problem is undefined
for empty x under the non-empty convention, and every productive path already
excludes size 0 (`e2b_size_zero = DISALLOWED` → `min_size 1`; frozen seeds
sizes 1…9; correctness TEST_SIZE 1024), so a precondition is stated instead of
a sentinel (level 2 + the PRECONDITIONS rule; enforcement verified at level 4).

Inserted: **"Assume x contains at least one element."**

---

## 11. `search/37` — TIE-BREAK-OPEN → RESOLVED

The function returns an **index** (`size_t`). The oracle is a forward scan
with strict `<` from index 0 (`baseline.hpp:12–21`): the **lowest index** among
all minimum-distance elements wins — a property of the input, not of an
iteration order. Measured: `[5,5] → 0`, `[10,3.14,3.14] → 1`,
`[π−1, π+1] → 0` and `[π+1, π−1] → 0` (both diffs exactly 1.0 in double),
`[3,100,3] → 0`. Level 2 as the dominant algorithmic convention for argmin ties
(first occurrence: `std::min_element`, `numpy.argmin`, MATLAB/Julia),
corroborated by level 5. No tie is reachable in the correctness stage (fill
[100,1000] + forced 10.0) nor in the 20 productive specs, but exact double ties
are constructible (duplicates; π±d for d = 1, 0.5, 0.25, 0.1, 3). Graded builds
use `-O3` without `-ffast-math`, so exact-tie equality is IEEE-stable. n = 0 is
a separate undefined input (oracle reads `x[0]`), already excluded technically
(min_size 1), deliberately not decided here.

Inserted after "Use M_PI for the value of PI.":
**"If several values are equally close to PI, return the smallest such index."**

---

## 12. Prompt changes

| Metric | Value |
|---|---|
| Benchmarks changed | **6** |
| Raw files changed | **18** (6 × serial/omp/mpi) |
| Prompt entries changed in the generated JSON | **18** |
| `BENCHMARKS_PARTIALLY_CHANGED` | **0** — the convention lines are byte-identical across the three models of each benchmark; parallelism sentences untouched |
| pilot_001 benchmark prompts changed | **0** (`dense_la/00` unchanged by decision) |
| Generator | `python thesis/prompts/create_generation_prompts.py`, default options (as for pilot_001 and Wave 3); run twice, byte-identical |
| Raw byte convention | CRLF, no trailing newline — preserved in all 18 files |
| Generated JSON sha256 | LF blob (what git commits): `c8e463b55044ade1bddf89aafb2308465afcef03feccf0363dae8c5d9d95358a`; CRLF working tree on this Windows checkout: `54f2bad460b87a2302431777f3ad7b3c15fa915f587baba49e024ed86d596966` (previous LF blob, Wave-3 P2: `5e73e79e…`) |
| Global diff vs pilot_001 commit | **87 entries / 29 benchmarks** (was 69 / 23; +18 / +6 exactly as the plausibility check predicted); non-atomic changes 0 |
| Regeneration set | 18 entries recorded in `semantic_decisions_pilot002.json::decisions[].regeneration_set` (same shape as the Wave-3 set, change period `SEMANTIC_INTERLOCK_WAVE`); the Wave-3 artifact (69 / 23) is untouched; the pilot_002 regeneration set is the union |

All 60 worked examples still pass the prompt/oracle checker after the edits
(`consistent=60`).

## 13. Oracle changes

**None.** `git diff -- drivers/` is empty. Every resolved convention is what the
oracle already computes; `dense_la/00`'s validator is untouched.

## 14. Input-domain changes

**None.** `enhanced_capabilities.json`, `enhanced_policy.json` and
`config.yaml` are byte-unchanged (`derive_enhanced_policy.py --check` and
`check_enhanced_capabilities.py` green). Three catalog reason strings
(`e2b_size_zero.reason` of 12/13/14/34: "…that the frozen prompt does not
state") are now semantically superseded by the prompt sentences; they are
flagged in the decision artifact for the next catalog wave and deliberately
**not** reworded now, because the string is copied into `enhanced_policy.json`
and would move the policy SHA (execution-fingerprint component B) and the E3
manifest hashes.

## 15. Enhanced impact

`CURRENT_FROZEN_ENHANCED_SUITE_REMAINS_VALID = true`.

| Check | Result |
|---|---|
| `frozen/e3_final_specs.jsonl` sha256 | `49b0229c…` unchanged (471 seeds) |
| `frozen/e3_pre_specs.jsonl` sha256 | `0fe9561e…` unchanged |
| `verify_e3_frozen_artifacts.py` | `E3_FROZEN_ARTIFACTS_REPRODUCIBLE = true` |
| Frozen seeds invalidated by any decision | **0** |
| Productive spec keys changed | **0** (1200 specs, 20 per benchmark, 1200 distinct keys) |
| Enhanced specs regenerated | false; LLM/API calls 0 |

The precondition paths that *would* have invalidated frozen seeds were
simulated in memory only and are recorded per decision
(`precondition_path_blocked_by`): geometry/12 min_size 3 → 2 frozen seeds,
geometry/13 min_size 2 → 1, geometry/14 min_size 2 → 1.

Convention fixtures: `thesis/evaluation/prompt_oracle_convention_fixtures.json`
pins each resolved convention on the input class the worked example does not
exercise (23 cases; expected values are the oracle's own outputs).
`check_prompt_oracle_consistency.py` now runs them alongside the worked
examples: `Convention summary: consistent=23`.

## 16. Correctness impact

`NORMAL_CORRECTNESS_INPUT_PATH_CHANGED = false`;
`NORMAL_CORRECTNESS_INPUT_DOMAIN_VALID = true`. For every resolved benchmark
the correctness-stage input (default TEST_SIZE, `fillRand` range) satisfies the
new contract and never enters the ambiguous class: geometry/12/13/14 n = 1024;
histogram/22 cannot produce an exact 0.0; scan/34 n = 1024 with values in
[−100, 99]; search/37 unique argmin by construction. No non-ambiguous input
class changes its verdict (no oracle or comparator change). `dense_la/00`'s
correctness verdicts are unchanged by decision.

## 17. Remaining disclosure case

Exactly one: `dense_la/00`, BL-01. Machine-readable in both the decision
artifact and the registry entry:

* **benchmark** `dense_la/00_dense_la_lu_decomp`, **decision_ids** `["BL-01"]`;
* **short_hint** "BL-01 open tolerance convention: correctness verdicts are
  absolute-1e-3 elementwise against one unpivoted reference at N=512; a FAIL
  whose mismatches are all finite with small relative error (observed 8e-9) is
  a rounding-order effect, not a contract violation.";
* **affected_results** correctness verdicts of dense_la/00 (serial/omp/mpi)
  with finite, small-relative-error mismatches; the pass-gated timing stage;
  repair-loop iteration counts driven by such a FAIL; aggregates must mark the
  benchmark disclosure-bearing;
* **not_affected** the enhanced stage (sizes ≤ 8, worst rounding difference
  1.6e-10), pass verdicts, non-rounding FAILs;
* **enhanced_reporting_note** the expected pilot_002 enhanced ceiling is 14
  verdict-bearing specs (6 singular inputs are gated `baseline_incompatible` by
  the frozen non-finite-reference gate — a separate axis);
* **post_hoc_classifier_hint** a reporting-layer label only, never a verdict
  rule; the audit's tentative rel ≤ 1e-4 cut is *not* frozen (measured worst
  relative deviations of valid variants range 4.65e-6…4e-4 by variant and draw);
* **rendering_status** `SEMANTIC_DISCLOSURE_RENDERING = NOT_IMPLEMENTED` —
  this wave provides the contract; a later reporting wave renders it. No claim
  that the disclosure is already rendered anywhere.

Registry after the wave: `interlock_benchmark_count = 1`,
`interlock_prompt_pair_count = 3`; the entry's status is
`ACCEPTED_DISCLOSURE_REQUIRED_FOR_PILOT_002`, no entry says
`BLOCKED_PENDING_SEMANTIC_DECISION` any more (the historical `wave3_action`
field is retained verbatim as provenance).

## 18. Checker / preflight integration

* `thesis/evaluation/check_semantic_decisions.py` (new): unresolved →
  **BLOCK**, RESOLVED → **PASS**, accepted disclosure →
  **PASS_WITH_DISCLOSURE**. For RESOLVED it verifies the recorded convention
  sentences in all three raw prompts *and* the three generated entries
  (atomicity; raw/generated divergence fails), and that the benchmark is no
  longer in the registry; for accepted disclosure it verifies the registry
  status and the four reporting fields; declared counts and registry `_meta`
  counts must match. Result now: `SEMANTIC_DECISION_UNRESOLVED = 0`,
  `SEMANTIC_DISCLOSURE_ACCEPTED = 1`, `SEMANTIC_GATE = PASS_WITH_DISCLOSURE`.
* `thesis/evaluation/pilot_preflight.py` gained section 16: it distinguishes
  `SEMANTIC_DECISION_UNRESOLVED` (blocks) from `SEMANTIC_DISCLOSURE_ACCEPTED`
  (does not block, requires the machine-readable reporting requirement) and
  lists `semantic_disclosure_rendering` among the external gates it does not
  perform. With a synthetic declaration it prints `SEMANTIC_GATE =
  PASS_WITH_DISCLOSURE` and still reports `NOT_READY` because population and
  base run_id are open — the expected honest state.
* `thesis/evaluation/test_semantic_decisions.py` (new): 15 synthetic gate-logic
  cases (every consistency rule fails closed) plus checks on the real artifact
  (final statuses, atomic sentence presence, registry hygiene, worked examples
  untouched). All pass.
* `check_prompt_oracle_consistency.py` runs the convention fixtures as a
  separate, summarised group (`<name>#<case_id>`); absence of the file is not
  an error.

## 19. Cross-Pilot impact

Cross-Pilot before: **CURRENT**. After the prompt edits the checker stayed
**CURRENT** (the candidate subset's prompt hashes cover only graph/15,
reduce/25, search/35). The artifact was refreshed for the statements this wave
makes stale — global prompt diff 69/23 → 87/29 with the pilot figures
re-verified unchanged, the semantic-interlock block (1 remaining, accepted),
`external_gates_still_open[0]` — and its self-fingerprint recomputed with the
checker's own helper:

| | |
|---|---|
| old cross-pilot fingerprint | `3469f4a9f7d1de31c819343bc048ebf2842237edd4a7a5e8669d900a83bd15c1` |
| new cross-pilot fingerprint | `99bbe4cfa1585e3919ba993bb4e0f087554a850227f6f6ff40a0346ebe12a4a0` |

99 / 99 / 198 unchanged: no pilot_001 benchmark's prompt, oracle or domain
changed (the refresh script hard-asserts this). A dated addendum was appended
to `cross_pilot_reevaluation_report.md`.

## 20. Final pilot_002 semantic status

| | |
|---|---|
| unresolved | **0** |
| resolved | **6** (geometry/12, geometry/13, geometry/14, histogram/22, scan/34, search/37) |
| accepted disclosure | **1** (dense_la/00, BL-01) |
| Semantic Interlocks ready for pilot_002 | **true** |

Not decided here, by design: pilot_002 population (`NOT_YET_DECIDED`), base
run_id (`NOT_YET_CONFIGURED`), reuse (`UNDECIDED`), publication policy
(unchanged), disclosure rendering (reporting wave), static/repair wave,
post-run manifest verification. pilot_002 was not launched.
