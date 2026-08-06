# Repair-Loop Design

Status: design final; fully implemented. Per-tool config incl.
low_confidence marking (tool_config.py), feedback/history formatter
(thesis/repair/feedback.py), driver mismatch patch (utilities.hpp +
patch_mismatch.py), loop orchestrator (thesis/repair/orchestrator.py,
run_repair.py; batch submission via thesis/generation/batch_api.py, which
moved out of this package on 2026-07-31 when the initial generation gained
a batch mode too — it mirrors the generation adapters and is now shared by
both stages), phase-2 backfill (thesis/repair/
run_backfill.py), consolidated overview (thesis/analysis_overview/
build_overview.py). This document is the single source of truth for the
repair-loop stage; the methodology chapter and the implementation both
derive from it.

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

**Feedback eligibility and low-confidence findings (validation-derived):**
Tool trustworthiness was measured on labeled suites (Juliet/DRB/MBI, see
thesis/tool_validation/). Findings from tools/finding-families whose
measured precision is below ~0.75 in their execution-model context are
NOT dropped but marked `low_confidence: true` (config:
`low_precision_warning` per tool; for clang_tidy per check_id family —
`clang-analyzer-optin.mpi.*` is low-confidence, generic clang-analyzer
findings are not). Currently low-confidence: parcoach (precision 0.51 on
MBI) and MPI-Checker findings (0.57 lax, 0.011 strict). In the feedback
prompt these render with the prefix "Low-confidence hint (tool precision
~0.5 on validation suites) — verify at the given location before
changing code:". Rationale: an uninformative gap is worse than an
honestly labeled weak hint, and verifying reports is part of the repair
capability under study.

**Stop semantics of low-confidence findings** (config
`low_confidence_stop_mode`): `ignore` | `grace_once` (default) |
`always_blocking`. Under grace_once a low-confidence finding counts as
blocking only while it is NEW (identity: check_id + line, the existing
dedupe key). If the same finding persists unchanged into the next
iteration, it stops counting: the model had one iteration to verify;
persistence with unchanged code means "checked, judged a false alarm".
A shifted line implies changed code — re-granting grace is then correct
behavior (the report is legitimately re-checkable after any change),
not a loophole. `always_blocking` exists for experiments only: permanent
warners like parcoach would drive every MPI loop to max_iterations.

Consequence for the ablation: variant A's MPI feedback consists almost
entirely of low-confidence hints (no trustworthy static MPI tool exists —
itself a key validation finding). Interpret A-vs-B on MPI samples as
"weak hints vs. dynamic feedback", not "static vs. dynamic analysis".

**Compressed history (per past iteration):**
- the cleaned code of that iteration (ParEval kernels are 30-100 lines;
  this enables the model to diff its own attempts and break repair
  cycles)
- findings as `line:check_id` + message truncated to ~80 chars
- B/C: test verdict only (e.g. "ParEval tests: FAIL (omp at 4/8
  threads)") — NOT the old mismatch numbers. **Corrected rationale
  (2026-08-06/07):** fillRand draws from unseeded `rand()` (as if
  `srand(1)`), so validation inputs are IDENTICAL across runs, models
  and iterations — verified twice: two driver runs are byte-identical,
  and the same expected value (e.g. `2.8866015260109088` at size 7,
  index 15) appears across all models' enhanced records. The original
  "old numbers refer to other random inputs" claim is therefore wrong.
  The rule stays for COMPRESSION: because the inputs are reproducible,
  the current iteration's report describes the same test completely —
  old expected/got add prompt tokens without adding information (they
  quantify the PREVIOUS code's output, which the model already sees as
  code in the history).

**Mismatch-report note:** ParEval's validate() only returns bool today.
The bounded expected/got report requires a mechanical driver patch of the
fequal comparison sites (same approach as patch_drivers.py: a
reportAndCompare helper in utilities.hpp, bounded output). Non-patchable
validate() structures (scalar comparisons etc.) fall back to PASS/FAIL
and are logged, as with the size patch. **Determinism note (2026-08-06,
for the methodology chapter):** the validation inputs come from unseeded
`rand()` and are therefore identical ACROSS runs and iterations — a
reproducibility plus (the same mismatch is re-observable), a diversity
minus (every run tests the same input draw; input diversity comes from
the enhanced-tests stage instead). Since 2026-08-06 the report prints
values at round-trip precision (max_digits10) plus a `rel=` relative
difference per line — previously the default 6-digit precision could
render a real difference as "expected=182071 got=182071"
(self-contradictory feedback, measured on smoke_002; two models ran to
stopped_budget on exactly that sample). `fequal` and the verdict
semantics are unchanged.

**Config-driven formatting (stages.repair):** everything
behavior-shaping is configured, not hardcoded (thesis/repair/feedback.py):

- `history_mode: compressed | full` — compressed is the format above;
  full renders past-iteration findings at current-feedback detail.
  Old mismatch numbers stay excluded in BOTH modes (old expected/got
  describe the previous code's output — see the corrected rationale
  above; the inputs themselves are identical across iterations).

  **Decision 2026-07-31 — the default is now `full`.** This document
  originally specified `compressed` as the default. Reversed for the main
  run: the repair loop is the object of study, so the model has to see
  the full finding detail of every past iteration. With compressed
  history a result like "the model kept reintroducing finding X across
  iterations" is not interpretable — it could equally mean the model was
  never told precisely enough. `full` removes that confound at a cost
  that is measured before it is spent: `run_repair.py --dry-run` renders
  each pending wave in BOTH modes and reports characters, estimated
  tokens and estimated cost side by side, so the decision can be revised
  per run with numbers rather than intuition.
- `feedback.include_non_blocking` (default false) — whether non-blocking
  findings (warnings, style, performance) are rendered, as a separate
  clearly-headed section after the blocking findings. Rendering only:
  non-blocking findings NEVER affect the stop criterion. Default false —
  the loop should fix errors, not discuss style; true is an experiment
  option ("does style feedback help or distract?").
- `feedback.low_confidence_prefix` — the verify-first hint text.
- `feedback.templates.*` — all prompt building blocks (headers,
  instruction) individually overridable.
- `feedback.history_message_max_chars`, `mismatch_report_max_indices` —
  the compression caps.
- `strategies.<name>.sources` — feedback sources per variant
  (compiler_errors | static_findings | correctness_verdicts |
  dynamic_findings); compiler_errors is the base in all three (compiler
  rule above). Within each source, only findings of config-enabled tools
  are rendered (tool_config is the single tool list).

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

**External-container tools (PARCOACH, LLOV).** These live in their own
images, so the loop cannot run them in-process.
`stages.repair.external_tools_mode` decides how they are handled:

- `manual` — the orchestrator writes the runner commands to
  `repair/<variant>/pending_external.txt`, parks the wave in
  `analyzed_waiting_external`, and continues once the records exist.
- `docker` (**default since 2026-07-31**) — the orchestrator starts the
  containers itself from `stages.repair.external_tool_commands`. Manual
  container handling per wave does not scale to 11 models x 3 variants x
  N iterations.

The docker mode is **docker-outside-of-docker**: the orchestrator runs
inside the toolchain container, which ships the docker CLI (docker/
Dockerfile) and must be started with
`-v /var/run/docker.sock:/var/run/docker.sock`. The sibling containers are
created by the HOST daemon, so their `-v` mounts need the HOST repo path —
templates use `{host_repo}`, filled from `stages.repair.host_repo_path` or
the `PAREVAL_HOST_REPO` environment variable (with `{repo}` still
available for the in-container path).

**Failure semantics (important for correctness of the results):** if a
container exits non-zero, or exits 0 without writing records, the wave
does NOT advance. It goes back to `analyzed_waiting_external`, writes
pending_external.txt and reports `blocked_external`. Advancing would
decide those samples with the external findings missing, i.e. silently
score a possibly-racy sample as clean. Only a MISSING TEMPLATE raises
immediately — that is a configuration bug, not a transient failure.

## 7. Batch orchestration (waves)

The loop is sequential per sample but runs in waves across samples:
all samples of (model, variant) at iteration n are generated, then all
analysis stages run, then iteration n+1. Each wave is one batch request
(~50% cost reduction on OpenAI/Anthropic/Gemini batch APIs; up-to-24h
latency overlaps with the analysis runs). The orchestrator therefore
needs an asynchronous state per wave: submitted -> polling -> results
merged (JSONL + resume, same pattern as generation/common.py).

**Initial generation uses the same mechanism (implemented 2026-07-31).**
`generation_defaults.api_mode: direct | batch` (plus per-provider
overrides) switches the generation stage to one batch job per model:
submit -> write `generation_batch.json` next to generations.jsonl ->
exit; `--poll` writes the records. It goes through the same
`thesis/generation/batch_api.py` as the loop, and — critically — through
the same record path (`common.apply_success` / `apply_failure`), so
cleaning, the truncated flag, refusal handling, sample_id assignment and
resume semantics cannot drift between the two modes. Providers without a
batch API (DashScope) fall back to direct with a log line. Relevance:
the full run is 180 samples x 11 models = 1980 generation calls.

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

**Cleaning interventions are part of the results.** The assembly stage
records per sample what it had to repair in the model output
(`auto_closed`, `used_fence`, `dropped_leading_lines`,
`relocated_includes`, `signature_suspect`). These land as `cleaning_*`
columns in the CSV and in their own summary section, because
`auto_closed` is an *intervention on the measured object*: the pipeline
closes braces the model left open, so a sample may only compile because
of our repair. That share must be stated wherever pass rates are
reported. The remaining flags describe the answer format and are an
instruction-following signal per model (the system prompt asks for bare
code without Markdown); split by iteration they also show whether models
change their answer format once they receive feedback.