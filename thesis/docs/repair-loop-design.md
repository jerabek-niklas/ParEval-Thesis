# Repair-Loop Design

Status: design agreed, not yet implemented. This document is the single
source of truth for the repair-loop stage; the methodology chapter and the
implementation both derive from it.

## 1. Purpose

Measure whether and how analysis feedback improves LLM-generated parallel
code: one initial generation per (model, prompt, execution model), followed
by up to 3 repair iterations driven by tool feedback. The core research
question is which *kind* of feedback helps (static analysis vs. testing +
dynamic analysis vs. everything), measured as an ablation over three loop
variants with identical starting points.

## 2. Variants (ablation design)

The initial generation is shared across variants (paired comparison). The
variants differ only in which feedback sources the loop may see:

| Variant | Feedback sources | Stop condition (own sources clean) |
| --- | --- | --- |
| A | static analysis only | no blocking static findings |
| B | ParEval tests + dynamic analysis | tests pass AND no blocking dynamic findings |
| C | all of the above | all of the above |

**Compiler rule (applies to all variants):** blocking compile *errors* are
base feedback in every variant — building is a precondition of any
execution, and every developer sees compiler errors; they are not an
"analysis finding" in the ablation sense. Compiler *warnings* count as
static analysis (variants A and C only).

Every variant additionally stops when the iteration budget (3) is
exhausted. Variant A may therefore stop while tests still fail ("statically
clean but incorrect") — this is a measured outcome, not a flaw.

## 3. Held-out principle: enhanced tests

Enhanced/extended test results (thesis/enhanced_tests) are **held out**
from the loop entirely:

- never part of the feedback prompt,
- never part of any stop condition (neither to stop nor to continue).

They are evaluated on **every iteration artifact** of every variant, purely
for analysis. This preserves the question "what would have slipped through
ParEval" across all iterations and enables the overfitting analysis:
if ParEval pass rates rise over iterations while enhanced pass rates
stagnate, the loop optimizes ParEval compliance rather than correctness —
plotted as a trajectory per variant.

Dynamic tools run **on ParEval inputs only** inside the loop (they are a
feedback source). Execution-parameter variation on enhanced inputs (axis 2)
is a separate, out-of-loop measurement, budget permitting.

## 4. Repair request format (stateless per iteration)

APIs are stateless; each repair request is fully self-contained. All code
shown to the model is the **cleaned, assembled** version (the exact bytes
the tools analyzed), so finding line numbers are referentially correct.
The model's repair answer goes through the normal assembly cleaning again.

```
[Original task prompt]
[Iteration 1: cleaned code + compressed findings/verdicts]
[Iteration 2: cleaned code + compressed findings/verdicts]
[Current version: cleaned code]
[Current feedback: full detail]
[Instruction: output the complete corrected function]
```

**Current feedback (full detail):**
- blocking findings as `line:check_id:message`, lines relative to the
  current cleaned code shown in the same request
- file field omitted (it is always the model file), with ONE exception:
  compile errors located in the driver TU are kept (see
  static-analysis-filtering.md) and translated for the model:
  "error at the call site in the test driver (your function
  name/signature likely does not match the expected interface):
  <compiler message>" — a raw `cpu.cc:57` reference would be
  meaningless or misleading to the model
- variants B/C: ParEval test verdict per launch grid point, plus a
  bounded mismatch report from the patched drivers (first k differing
  indices with expected/got and the input values at those indices)

**Compressed history (per past iteration):**
- the cleaned code of that iteration (ParEval kernels are 30-100 lines;
  this enables the model to diff its own attempts and break repair
  cycles)
- findings as `line:check_id` + message truncated to ~80 chars
- B/C: test verdict only (e.g. "ParEval tests: FAIL (omp at 4/8
  threads)") — NOT the old mismatch numbers: fillRand inputs differ per
  run (no persisted seed), so old expected/got values refer to other
  inputs and would mislead

**Mismatch-report note:** ParEval's validate() only returns bool today.
The bounded expected/got report requires a mechanical driver patch of the
fequal comparison sites (same approach as patch_drivers.py: a
reportAndCompare helper in utilities.hpp, bounded output). Non-patchable
validate() structures (scalar comparisons etc.) fall back to PASS/FAIL
and are logged, as with the size patch. Feedback is symptom-level, not a
reproducible test case (random inputs, no seed) — state this in the
methodology chapter.

## 5. Iteration mechanics and ID schema

- Record identity: `sample_id` x `variant` (A|B|C) x `iteration` (0..3),
  iteration 0 = shared initial generation.
- Each iteration artifact runs the full stage chain: assembly ->
  compile/static -> correctness -> dynamic (per variant needs) ->
  enhanced tests (always, held-out evaluation).
- Iteration n+1 starts from the assembled file of iteration n (not the
  raw model output).
- A repair answer that fails assembly (unparseable) ends the sample's
  loop with status `repair_unusable` — logged, not silently dropped.

## 6. Execution phases: lean loop, full backfill

The run is split into two phases. Phase 1 (the loop) executes per variant
only what its stop condition and feedback require; phase 2 (backfill)
runs everything else over all persisted iteration artifacts afterwards.

**Phase 1 — loop-time minimum per variant:**

| Variant | Runs during the loop |
| --- | --- |
| A | compile + static tools |
| B | compile + ParEval correctness + dynamic tools |
| C | compile + static + ParEval correctness + dynamic |

Enhanced tests run in NO variant during the loop. Consequence for wave
planning: A-waves are fast (minutes), B/C-waves are dominated by the
dynamic runs; variants are independent and their batches may proceed in
parallel at different speeds.

**Phase 2 — backfill for analysis:** after all loops have terminated,
run the missing tools and test sets over every persisted iteration
artifact (every assembled generated-code.hpp): static tools over B
artifacts, correctness + dynamic over A artifacts, enhanced tests over
everything. This is local compute only (no API cost), interruptible and
resumable, and parallelizable across artifacts.

This structure enforces the held-out principle **structurally**: during
the loop, enhanced results and non-variant tool results do not exist, so
no implementation bug can leak them into feedback or stop decisions.

**Environment consistency:** phase 2 must run in the same container
images as phase 1, otherwise backfilled findings are not comparable with
loop-time findings (different tool versions, different checks). The
backfill runner compares /opt/toolchain-versions.txt of both phases and
warns on any mismatch.

## 7. Batch orchestration (waves)

The loop is sequential per sample but runs in waves across samples:
all samples of (model, variant) at iteration n are generated, then all
analysis stages run, then iteration n+1. Each wave is one batch request
(~50% cost reduction on OpenAI/Anthropic/Gemini batch APIs; up-to-24h
latency overlaps with the analysis runs). The orchestrator therefore
needs an asynchronous state per wave: submitted -> polling -> results
merged (JSONL + resume, same pattern as generation/common.py). Initial
generation is trivially batchable.

## 8. Cost estimate (rough)

Per model: 180 samples (60 prompts x 3 execution models). Without repair:
180 requests. With 3 variants x up to 3 iterations: worst case
180 x (1 + 9) = 1800 requests per model, in practice fewer (stop
conditions). Requests are small (task + a few kernel versions of
30-100 lines). With batch pricing, the full run is roughly 1.25x the
cost of the originally planned single-variant loop without batching.
Recompute with real token counts after the first wave.

## 9. Evaluation outputs

Per (variant, iteration): blocking findings per tool/class, ParEval pass
rate, enhanced pass rate (held-out), stop-reason distribution,
iterations-to-clean. Key analyses: variant comparison (which feedback
kind helps, at what cost), ParEval-vs-enhanced trajectories
(overfitting), per problem-type breakdown, "statically clean but
incorrect" rate for variant A.

## 10. Consolidated overview (analysis layer)

A single script joins all stage JSONLs (correctness, static, dynamic,
enhanced, repair metadata) on `sample_id x variant x iteration` and
produces two artifacts:

- **flat CSV**: one row per (sample, variant, iteration) with columns
  for all verdicts and counts (build ok, ParEval verdict per grid
  point, blocking findings per tool, enhanced pass/fail counts, stop
  reason, durations). This is the basis for every plot and table in
  the thesis (same role as upstream's create-dataframe.py).
- **markdown summary**: the core aggregates — pass-rate trajectories
  per variant (ParEval vs. enhanced, the overfitting view), stop-reason
  distribution, findings per tool/class, per problem-type breakdown.

Joins must tolerate missing records (e.g. `repair_unusable` samples
have no later iterations) and mark them explicitly rather than
dropping rows silently.
