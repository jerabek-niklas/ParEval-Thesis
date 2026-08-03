# Timing and effort measurements

What the pipeline measures about time and model effort, and how those
numbers may be interpreted. Implemented in
[`thesis/generation/common.py`](../generation/common.py) (record fields),
[`thesis/generation/validate_generations.py`](../generation/validate_generations.py)
(enforcement) and
[`thesis/analysis_overview/build_overview.py`](../analysis_overview/build_overview.py)
(aggregation). Record changes are additive (schema `generation.v3`);
existing fields keep their names and meaning.

## What is measured

| Measurement | Field(s) | Available in | Meaning |
| --- | --- | --- | --- |
| Direct request latency | `status.duration_seconds` (with `status.timing_mode == "direct"`) | direct mode only | Wall time of the synchronous API call, including retries |
| Batch wall time | `status.batch_submitted_at_utc` / `status.batch_completed_at_utc` (`timing_mode == "batch"`) | batch mode only | Submit-to-completion span of the whole job — **queue time, not latency** (see below) |
| Model effort | `api_response.usage_normalized` (`input_tokens`, `output_tokens`, `reasoning_tokens`) | both modes | Tokens spent, provider-independent |
| Tool runtime | `duration_seconds` per tool entry in the stage JSONLs; `<tool>_seconds` / `<tool>_timed_out` in overview.csv | all analysis stages | Per-sample analysis cost of each tool |

## Why batch durations are not latency

In batch mode the measurable span (submit → result) is dominated by the
**provider's batch queue** — up to 24 h, depending on load and time of
day — and the batch APIs do not expose the actual per-request inference
time. The span therefore says nothing about the model. Consequences,
enforced by `validate_generations.py`:

- batch records carry `status.duration_seconds: null` (not 0, not the
  wait time) — the column stays clean for aggregation;
- the span is recorded as two timestamps that cannot be mistaken for a
  latency measure;
- **batch and direct durations must never be mixed in one evaluation.**
  The overview's latency table filters on `timing_mode == "direct"`.

**Legacy `generation.v2` files:** batch mode already existed under v2 and
stamped a near-zero *poll-side processing* duration onto batch records
with no marker in the record. The overview therefore classifies legacy
records (no `timing_mode`) by, in order: the repair-batch marker
`generation_parameters.api_mode`, then the run summary's `api_mode`, then
"direct" (summaries predating the batch feature have no `api_mode`; those
runs were all synchronous). Anything classified batch contributes no
latency. No v2 batch file exists in the repository's runs today — the
rule guards re-analysis of archived or future data.

## Why reasoning tokens are the primary effort metric

Wall-clock seconds measure the model *plus* the network, the provider's
load, and (in batch mode) a queue. Reasoning tokens measure only what the
model spent on the task, are reported in **both** API modes, and are
comparable across providers. `usage_normalized` maps the five provider
formats onto one view; the raw `usage` is always kept verbatim:

| Provider | Reasoning-token field (raw usage) |
| --- | --- |
| OpenAI (Responses API) | `output_tokens_details.reasoning_tokens` |
| Anthropic | `output_tokens_details.thinking_tokens` |
| Gemini | `thoughts_token_count` (flat, no details object) |
| DashScope (Qwen/DeepSeek) | `completion_tokens_details.reasoning_tokens` |

`reasoning_tokens: null` means the provider reports no such field —
distinct from an explicit `0`, which adaptive-thinking models
legitimately produce on easy tasks (measured for Anthropic in
model-set.md). Every successful record of a model that the reasoning
policy configures to think is checked at write time: a missing field
logs a warning (the parameter may be silently ignored — the running
continuation of the one-off probes in model-set.md), a zero logs a
softer note.

## Tool runtimes in the overview

`overview.csv` carries one `<tool>_seconds` column per pipeline tool plus
`<tool>_timed_out`, and the stage sums `static_seconds`,
`dynamic_seconds`, `correctness_seconds`, `enhanced_seconds`
(`duration_analysis_seconds` remains the pre-existing static+dynamic
combination). The summary section "Runtime cost per tool" reports
**median and p95** per tool × execution model — medians because the
distributions are skewed (MUST deadlock timeouts, Valgrind's 20–50×
slowdown would dominate any mean). Timed-out runs are excluded from
median/p95 and reported as their own share: their recorded duration is
the configured limit, not a measured analysis time.

Shared iteration-0 rows are deduplicated before aggregation (every
variant references the same initial-generation records; counting them per
variant would multiply identical measurements).

## Interpreting direct latency

Direct latency additionally depends on the network path and the
provider's momentary load. If latency is to be *reported as a result*, it
must come from **one contiguous direct run** (e.g. the smoke run), not
from runs spread over days — the per-day variance of provider load is
visible even in this project's own probes (Infer aside: the same request
measured 20–48 s within one session). The overview labels its latency
table accordingly and never mixes in batch records.
