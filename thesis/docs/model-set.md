# Model Set (11 models)

Last change: **2026-07-31** — `claude_opus_5` replaces `claude_opus_48`
in the Anthropic slot (count unchanged at 11 enabled models; the 4.8
entry stays disabled, see the table).

Verification date: **2026-07-21**. Every API id was verified against the
provider's live models endpoint (`GET /models`); availability was
additionally proven by one real generation call per new model through the
normal pipeline (`generate.py --profile model_check`, run
`model_check_001` — records carry success, finish_reason, and token
usage). Prices are list prices per 1M tokens from provider docs /
aggregators retrieved on the same date; the DashScope prices are for the
international endpoint (our deployment: `eu-central-1.maas.aliyuncs.com`)
— regional pricing can differ.

## Table

| Config id | Verified API id | Reachable | Batch | Price in/out per 1M | Retrieved |
| --- | --- | --- | --- | --- | --- |
| `claude_opus_5` | `claude-opus-5` | yes (models endpoint + smoke 2026-07-31) | yes (Message Batches, implemented in batch_api.py, not live-tested) | $5.00 / $25.00 (batch $2.50 / $12.50) | 2026-07-31 |
| ~~`claude_opus_48`~~ | `claude-opus-4-8` | **disabled 2026-07-31** — superseded by Opus 5 (entry kept, id not recycled, so earlier records stay attributable) | — | $5.00 / $25.00 | 2026-07-21 |
| `claude_fable_5` | `claude-fable-5` | yes (smoke 2026-07-21; models endpoint reports `batch: supported`) | yes (Message Batches, implemented, not live-tested) | $10.00 / $50.00 | 2026-07-21 |
| `openai_gpt55` | `gpt-5.5` | yes (full pipeline runs) | yes (file-based Batch API `/v1/responses`, implemented, not live-tested) | $5.00 / $30.00 | 2026-07-21 |
| `openai_gpt56_sol` | `gpt-5.6-sol` | yes (smoke 2026-07-21) | yes (Batch API, implemented, not live-tested) | $5.00 / $30.00 | 2026-07-21 |
| `gemini_31_pro` | `gemini-3.1-pro-preview` | yes (full pipeline runs) | yes (inline batch, implemented, not live-tested) | $2.00 / $12.00 (≤200K prompt; $4/$18 above) | 2026-07-21 |
| `gemini_36_flash` | `gemini-3.6-flash` | yes (smoke 2026-07-28) | yes (inline batch, implemented, not live-tested) | $1.50 / $7.50 (input unchanged vs 3.5, output down from $9.00) | 2026-07-28 |
| ~~`gemini_35_flash`~~ | `gemini-3.5-flash` | **disabled 2026-07-28** — superseded by 3.6 Flash (entry kept, not recycled, so older records stay attributable) | — | $1.50 / $9.00 | 2026-07-21 |
| `qwen37_max` | `qwen3.7-max` | yes (smoke 2026-07-21) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $1.25 / $3.75 | 2026-07-21 |
| `qwen3_coder_api` | `qwen3-coder-plus` | yes (full pipeline runs) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $0.65 / $3.25 | 2026-07-21 |
| `qwen36_35b_a3b` | `qwen3.6-35b-a3b` | yes (smoke 2026-07-21) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $0.14 / $0.90 | 2026-07-21 |
| `deepseek_v4_pro` | `deepseek-v4-pro` | yes (full pipeline runs) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $0.435 / $0.87 | 2026-07-21 |
| `deepseek_v4_flash` | `deepseek-v4-flash` | yes (smoke 2026-07-21) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $0.14 / $0.28 (cache-miss input) | 2026-07-21 |

Undated aliases are used throughout (consistent with the existing
entries); DashScope additionally lists dated snapshots
(`qwen3.7-max-2026-06-08` etc.) that the alias tracks.

## Selection rationale

- **Anthropic — generation pair:** `claude-opus-5` vs. `claude-fable-5`
  measures progress across two model generations of the same vendor under
  identical prompts. **Opus swap 2026-07-31:** Opus 5 replaced Opus 4.8;
  the 4.8 entry is kept disabled rather than recycled, so the smoke_001 /
  model_check_001 / repair_smoke_001 records stay attributable to the
  model that produced them (same convention as the Flash swap).
- **OpenAI — generation pair:** `gpt-5.5` vs. `gpt-5.6-sol` (the 5.6
  flagship tier) is the same cross-generation comparison on the OpenAI
  side.
- **Google — class pair:** `gemini-3.1-pro-preview` vs.
  `gemini-3.6-flash` contrasts the Pro class against the Flash class
  (no 3.x Pro beyond 3.1 is GA, see below, so the class pair spans
  generations). **Flash swap 2026-07-28:** 3.6 Flash replaced 3.5 Flash
  because it is GA, more token-efficient and cheaper at better
  code/agent capability (Google release notes); the class-pair role is
  unchanged. The 3.5 entry stays in the config as `enabled: false` —
  IDs are never recycled, so records from earlier runs remain
  attributable to the model that produced them.
- **DeepSeek — size pair:** `deepseek-v4-pro` vs. `deepseek-v4-flash`
  isolates model size within one generation and vendor.
- **Alibaba — three roles:** `qwen3.7-max` (closed flagship),
  `qwen3-coder-plus` (code specialist), `qwen3.6-35b-a3b` (best
  open-weight generalist of the line, MoE 35B total / 3B active).

## Batch capability

- **Anthropic / OpenAI / Gemini:** batch endpoints are implemented in
  `thesis/repair/batch_api.py` (Message Batches, `/v1/batches` +
  `/v1/responses`, google-genai inline batch). Configured, deliberately
  NOT live-tested (per task scope); verify on the first real batch wave.
- **DashScope (Qwen + DeepSeek, provider `openai_compatible`):** a
  2-request mini-batch was attempted on 2026-07-21 via
  `batch_api.submit_batch` against our deployment's base URL. Result: the
  EU Model-Studio gateway (`ws-….eu-central-1.maas.aliyuncs.com`) returns
  **404 on both `POST /v1/files` (purpose=batch) and `/v1/batches`** —
  the OpenAI-compatible batch flow does not exist on this endpoint.
  Consequence: `api_mode_overrides` stays empty; under a global
  `api_mode: batch` the orchestrator automatically falls back to direct
  for `openai_compatible` (logged). Note: the public international
  DashScope endpoint (`dashscope-intl.aliyuncs.com/compatible-mode/v1`)
  documents a batch API — if the deployment ever moves there, re-run the
  mini-batch test before forcing batch.

## Reasoning policy

**Policy:** middle — or, where a middle level would be a de-facto
throttle, the lowest practically effective — reasoning level of each
model's own scale; token budgets set non-constraining; every exception
technically justified and documented (config.yaml comments + this
table). Verified 2026-07-21 by per-model structure probes
(thinking-output location, final parameter combinations) and a full
`model_check` pass over all 11 models with the final settings.

| Config id | Parameter | Level set | Controllable | Thinking output | Deviation / justification |
| --- | --- | --- | --- | --- | --- |
| `openai_gpt55` | `reasoning_effort` | `medium` | yes (effort scale) | separate (Responses API reasoning items; never in `output_text`) | — |
| `openai_gpt56_sol` | `reasoning_effort` | `medium` | yes | separate | — |
| `gemini_31_pro` | `thinking_level` | `medium` | yes (low/medium/high) | separate (thought parts; adapter reads answer text only) | — |
| `gemini_36_flash` | `thinking_level` | `medium` | yes (MINIMAL/LOW/MEDIUM/HIGH; probe 2026-07-28 accepted) | separate | 3.5/3.6 scale adds MINIMAL → "medium" is the middle of each series' own scale, not an exactly equivalent point across 3.1/3.6 |
| ~~`gemini_35_flash`~~ | `thinking_level` | `medium` | — | separate | disabled 2026-07-28 (superseded by 3.6 Flash) |
| `glm_5_2` (spec generator, not evaluated) | `enable_thinking` | provider default (ON) | partially (on/off) | separate `reasoning_content`; `message.content` is clean strict JSON (probe 2026-07-28) | not part of the evaluation set — listed for completeness |
| `claude_opus_5` | `effort` | `medium` | partially (depth via effort low/medium/high/xhigh/max; thinking itself is on) | thinking blocks, separate; adapter extracts text blocks only | NO activation field needed — unlike Opus 4.8, Opus 5 thinks without one (probe below). Same configuration as its pair partner claude_fable_5 |
| ~~`claude_opus_48`~~ | `thinking: adaptive` + `effort` | `medium` | yes | thinking blocks, separate | disabled 2026-07-31 (superseded by Opus 5). Thinking had to be ACTIVATED here — omitting the parameter ran without thinking; that is why the adapter grew the `thinking` field in the first place |
| `claude_fable_5` | `effort` | `medium` | partially (depth via effort; thinking itself cannot be disabled) | thinking blocks (omitted by default), separate | always-on thinking needs no activation field; SAME effort level as the Opus pair partner |
| `qwen37_max` | `enable_thinking` + `thinking_budget` | ON, budget 8192 | partially (on/off + token budget; NO level scale) | separate `reasoning_content` | budget chosen non-constraining (well above observed spend, below the 16384 output cap) — it must not become the limiting factor |
| `qwen3_coder_api` | — | none | no (non-thinking model; `enable_thinking` silently ignored) | none | DOCUMENTED EXCEPTION: the model has no thinking to configure |
| `qwen36_35b_a3b` | `enable_thinking` + `thinking_budget` | ON, budget 8192 | partially (on/off + budget) | separate `reasoning_content` | same as qwen37_max |
| `deepseek_v4_pro` | `enable_thinking` + `reasoning_effort` + `thinking_budget` | ON, `high`, budget 8192 | partially (on/off + effort + token budget) | separate `reasoning_content` | `high` = LOWEST practically effective level of the DeepSeek scale — `medium` would be a de-facto throttle. **`thinking_budget` 8192 added 2026-08-05 (required):** unbounded, `high` can spend the ENTIRE `max_tokens` on reasoning — measured on smoke_002 combined_feedback iter1, sample `deepseek_v4_pro__dense_la__00_dense_la_lu_decomp__serial__sample_0`: 16384/16385 completion tokens were reasoning, content EMPTY, `finish_reason: length`, deterministic over 3 retries. With the budget the same request answers cleanly (reasoning capped at exactly 8192, `finish_reason: stop`). Non-constraining for normal spend (probes: 112–1721 tokens) |
| `deepseek_v4_flash` | `enable_thinking` + `reasoning_effort` + `thinking_budget` | ON, `high`, budget 8192 | partially | separate `reasoning_content` | same as v4_pro (size pair runs one setting; budget acceptance verified for flash 2026-08-05) |

Probe evidence (2026-07-21; structure probes per DashScope model with
the FINAL parameter combinations — qwen with thinking_budget 8192,
deepseek with reasoning_effort high): no DashScope model ever emitted
inline `<think>` blocks in `message.content` — thinking always arrives
as a separate `reasoning_content` field, so the assembly cleaning is
unaffected and the openai_compatible adapter needs no change
(`_extract_text` reads `message.content` exclusively;
`reasoning_content` is discarded, reasoning token counts are logged via
`usage` in the generation records).

### Effect evidence: the parameters are not just sent, they act (2026-07-31)

"The parameter is transmitted" is not "the parameter takes effect" —
DashScope has historically ignored thinking options in non-streaming mode.
One **non-streaming** call per model through the real pipeline adapter,
inspecting `usage` and `message.reasoning_content`:

| Config id | `reasoning_tokens` (usage) | `reasoning_content` chars | inline `<think>` | verdict |
| --- | --- | --- | --- | --- |
| `qwen37_max` | 603 | 2 055 | no | thinking ACTIVE |
| `qwen36_35b_a3b` | 1 721 | 6 614 | no | thinking ACTIVE |
| `deepseek_v4_pro` | 302 | 1 264 | no | thinking ACTIVE |
| `deepseek_v4_flash` | 112 | 455 | no | thinking ACTIVE |
| `qwen3_coder_api` | — (`completion_tokens_details` is `null`) | — | no | no thinking, as documented (non-thinking model) |

So **no model needed a streaming call**, and the streaming option (which
would change the response path and therefore record construction) is not
required — it stays unused, not even as a fallback.

**Anthropic, checked in the same pass because the `model_check_001`
records showed `output_tokens_details.thinking_tokens: 0`:** that is
adaptive thinking working as specified, not an ignored parameter. On a
trivial prompt (sum of a vector) both models spend 0 thinking tokens; on
a real MPI LU-factorization prompt `claude_opus_48` spends 1 013 and
`claude_fable_5` 180 thinking tokens with the identical settings. A zero
in a record is therefore a property of the task, not of the
configuration — worth stating in the methodology chapter, because
per-sample thinking-token counts will legitimately be 0 for easy
benchmarks.

**Opus 5 needs no activation field (probe 2026-07-31).** The same MPI LU
prompt against `claude-opus-5` with three parameter combinations:

| Sent | thinking tokens |
| --- | --- |
| `{}` (no thinking field, no effort) | 806 |
| `{"output_config": {"effort": "medium"}}` | 310 |
| `{"thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"}}` | 559 |

The decisive observation is the first row: with an EMPTY payload Opus 5
still thinks, where Opus 4.8 returns 0. Thinking is therefore on by
default, as on Fable 5, and `claude_opus_5` is configured with `effort`
only — which also makes the Anthropic pair symmetric in both fields.
Sending `thinking: adaptive` remains valid (row 3) but would document a
requirement that does not exist. The token COUNTS across the three rows
are single samples and vary by hundreds; they are not a controlled
comparison and no effort-vs-depth conclusion is drawn from them.

**Addendum 2026-08-08 (smoke_004 follow-up; A/B probe on the LU prompts
with the pipeline system prompt):** adaptive thinking on Fable 5 is
strongly PROMPT-DEPENDENT — serial/omp LU prompts: 0 thinking tokens
(no thinking block), mpi: ~80–90, effort high slightly more; with and
without an explicit `thinking: adaptive` field the numbers match
(smoke_004 iteration 0 without the field: 0/0/89). smoke_004's
"reasoning median 0" was therefore genuine model behavior on easy
prompts, NOT a capture bug — the raw
`output_tokens_details.thinking_tokens` equals `usage_normalized.
reasoning_tokens` exactly, and the same cross-check against live
records confirmed the field paths of all five providers. Consequences:
(a) all Anthropic config entries now set `thinking: adaptive`
explicitly (behaviorally a no-op on 5-series, mandatory on 4.8 —
uniform and self-documenting); (b) the 0-token reasoning-evidence
warning is persisted in `generation_summary.json` (stdout alone
scrolled past unseen).

Where the reasoning-token count lives per provider (all persisted in
`api_response.usage` of the generation record, so the methodology chapter
and the cost accounting can read it straight from the JSONL):

| Provider | Field |
| --- | --- |
| OpenAI (Responses) | `output_tokens_details.reasoning_tokens` |
| Anthropic | `output_tokens_details.thinking_tokens` |
| Gemini | `thoughts_token_count` |
| DashScope (Qwen/DeepSeek) | `completion_tokens_details.reasoning_tokens` |

### Gemini sampling parameters are deprecated (affects the "greedy decoding" claim)

`temperature`, `top_p` and `top_k` are deprecated in the current Gemini
API. A probe against `gemini-3.6-flash` (2026-07-28) shows they are still
**accepted without error or warning** — so this was not a breakage — but
the adapter no longer sends them (`generate-gemini.py`), for two reasons:
a deprecated parameter can disappear at any API version, and with
thinking enabled `temperature: 0` no longer buys the greedy, reproducible
decoding it was configured for. Consequence for the methodology chapter:
the statement "greedy decoding, sent to the models that support it
(Gemini, Qwen, DeepSeek)" **no longer covers Gemini** — Gemini models now
run at provider-default sampling, like the OpenAI and Anthropic models
(which never accepted the parameters). Records written from 2026-07-28
onward log `temperature: null` / `top_p: null` for Gemini; earlier Gemini
artifacts were produced with `temperature: 0` and differ on this axis.

## Test-case generator (not part of the evaluation set)

The enhanced-tests input specs are generated by
`stages.enhanced_tests.spec_model`. Since 2026-07-28 that is **`glm_5_2`
(GLM / Zhipu, `glm-5.2`)**, configured with `enabled: false` so it can
never join a generation run.

| Property | Value |
| --- | --- |
| Verified API id | `glm-5.2` (models endpoint of our deployment, 2026-07-28; `glm-5.1` also listed, `glm-5` / `glm-4.7` are not) |
| Access | existing Model Studio key — the endpoint hosts third-party models next to Qwen, so no new provider adapter and no new account |
| Output structure | thinking in a separate `reasoning_content` field; `message.content` is clean strict JSON — no `<think>` blocks, no markdown fences (probe 2026-07-28), which is what `generate_test_specs.py` requires |

**Why a family outside the evaluation set:** an evaluated model writing
the test cases it is later judged on invites a same-family advantage.
GLM is in neither the evaluated set nor any evaluated model's family.
The safeguard is structural rather than statistical, and it does not
stand alone: the **oracle is always the serial baseline implementation**,
never the generator — the generator only proposes input shapes, and every
spec additionally passes the baseline gate (crash/hang plus numerical
stability) before it can count against any model. Earlier generators
(`openai_gpt55`, then `openai_gpt56_sol`) were part of the evaluation
set; their spec sets are archived under
`results/cache/enhanced/archive/` so a generator comparison remains
possible.

### Remaining asymmetry (known comparability limit for the methodology chapter)

The policy normalizes *settings within each vendor's own scale*, not
reasoning *budgets* across vendors — the scales are structurally
different: OpenAI and Claude use effort levels, Gemini uses
thinking_level (with a 3.5-only MINIMAL step), Qwen has only on/off
plus a token budget, and DeepSeek has on/off plus an effort knob whose
lower levels are practically inert (hence `high` as the lowest
effective level). `qwen3-coder-plus` cannot think at all — it is the
one model measured without reasoning. Reasoning-token spend therefore
differs by design across vendors; cross-vendor comparisons measure
each model at its policy-mapped setting, while the within-vendor pairs
(gpt-5.5 vs gpt-5.6-sol, Opus 5 vs Fable 5, DeepSeek pro vs flash)
run pairwise-identical settings and stay internally consistent.
Additionally: pipeline artifacts produced BEFORE 2026-07-21 (e.g.
smoke_001) ran the DeepSeek models with thinking disabled and Claude
Opus 4.8 without thinking — results from those runs are not comparable
to post-policy runs on this axis. From 2026-07-31 the Anthropic slot is
`claude_opus_5`, so all Opus 4.8 artifacts belong to the pre-swap set as
well; they keep their own model id and are never merged with Opus 5
results.

## spec_model candidates (information only, config unchanged)

| Candidate | Available? | Price in/out per 1M | Note |
| --- | --- | --- | --- |
| `gpt-5.6-luna` | yes — listed on the OpenAI models endpoint (2026-07-21) | $1.00 / $6.00 | cheapest 5.6 tier; would replace `openai_gpt55` as spec model|
| `gemini-3.5-pro` | **no** — not GA; absent from the Gemini models endpoint (2026-07-21); press coverage confirms it has not shipped (3.1 Pro remains the Pro tier) | n/a | re-check before the full run |

Current `stages.enhanced_tests.spec_model` remains `openai_gpt55`
(unchanged).

## Sources (retrieved 2026-07-21)

- Anthropic model ids/prices: Anthropic models endpoint +
  platform.claude.com models overview (skill reference cache 2026-06-24)
- GPT-5.6 tiers/prices: [aipricing.guru](https://www.aipricing.guru/openai-pricing/),
  [apidog](https://apidog.com/blog/gpt-5-6-pricing/),
  [benchlm.ai](https://benchlm.ai/openai/api-pricing)
- GPT-5.5 price: [devtk.ai](https://devtk.ai/en/models/gpt-5-5/),
  [openrouter](https://openrouter.ai/openai/gpt-5.5)
- Gemini 3.5 Flash price / 3.5 Pro status:
  [benchlm.ai](https://benchlm.ai/google/api-pricing),
  [pricepertoken](https://pricepertoken.com/pricing-page/model/google-gemini-3.5-flash),
  [tokenmix](https://tokenmix.ai/blog/gemini-3-5-pro-release-date-google-io-2026)
- Qwen prices: [pricepertoken](https://pricepertoken.com/pricing-page/provider/qwen),
  [openrouter qwen3-coder-plus](https://openrouter.ai/qwen/qwen3-coder-plus)
- DeepSeek prices: [benchlm.ai](https://benchlm.ai/deepseek/api-pricing),
  [api-docs.deepseek.com](https://api-docs.deepseek.com/quick_start/pricing/)
