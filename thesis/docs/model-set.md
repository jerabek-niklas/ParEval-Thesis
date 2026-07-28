# Model Set (11 models)

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
| `claude_opus_48` | `claude-opus-4-8` | yes (full pipeline runs) | yes (Message Batches, implemented in batch_api.py, not live-tested) | $5.00 / $25.00 | 2026-07-21 |
| `claude_fable_5` | `claude-fable-5` | yes (smoke 2026-07-21; models endpoint reports `batch: supported`) | yes (Message Batches, implemented, not live-tested) | $10.00 / $50.00 | 2026-07-21 |
| `openai_gpt55` | `gpt-5.5` | yes (full pipeline runs) | yes (file-based Batch API `/v1/responses`, implemented, not live-tested) | $5.00 / $30.00 | 2026-07-21 |
| `openai_gpt56_sol` | `gpt-5.6-sol` | yes (smoke 2026-07-21) | yes (Batch API, implemented, not live-tested) | $5.00 / $30.00 | 2026-07-21 |
| `gemini_31_pro` | `gemini-3.1-pro-preview` | yes (full pipeline runs) | yes (inline batch, implemented, not live-tested) | $2.00 / $12.00 (≤200K prompt; $4/$18 above) | 2026-07-21 |
| `gemini_35_flash` | `gemini-3.5-flash` | yes (smoke 2026-07-21) | yes (inline batch, implemented, not live-tested) | $1.50 / $9.00 | 2026-07-21 |
| `qwen37_max` | `qwen3.7-max` | yes (smoke 2026-07-21) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $1.25 / $3.75 | 2026-07-21 |
| `qwen3_coder_api` | `qwen3-coder-plus` | yes (full pipeline runs) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $0.65 / $3.25 | 2026-07-21 |
| `qwen36_35b_a3b` | `qwen3.6-35b-a3b` | yes (smoke 2026-07-21) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $0.14 / $0.90 | 2026-07-21 |
| `deepseek_v4_pro` | `deepseek-v4-pro` | yes (full pipeline runs) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $0.435 / $0.87 | 2026-07-21 |
| `deepseek_v4_flash` | `deepseek-v4-flash` | yes (smoke 2026-07-21) | no — endpoint lacks /v1/batches (404, tested 2026-07-21) → direct | $0.14 / $0.28 (cache-miss input) | 2026-07-21 |

Undated aliases are used throughout (consistent with the existing
entries); DashScope additionally lists dated snapshots
(`qwen3.7-max-2026-06-08` etc.) that the alias tracks.

## Selection rationale

- **Anthropic — generation pair:** `claude-opus-4-8` vs. `claude-fable-5`
  measures progress across two model generations of the same vendor under
  identical prompts.
- **OpenAI — generation pair:** `gpt-5.5` vs. `gpt-5.6-sol` (the 5.6
  flagship tier) is the same cross-generation comparison on the OpenAI
  side.
- **Google — class pair:** `gemini-3.1-pro-preview` vs.
  `gemini-3.5-flash` contrasts the Pro class against the Flash class
  (gemini-3.5-pro is not GA, see below, so the class pair spans
  generations).
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
| `gemini_35_flash` | `thinking_level` | `medium` (= 3.5 default) | yes (MINIMAL/LOW/MEDIUM/HIGH) | separate | 3.5 scale adds MINIMAL → "medium" is the middle of each series' own scale, not an exactly equivalent point across 3.1/3.5 |
| `claude_opus_48` | `thinking: adaptive` + `effort` | `medium` | yes (effort low/medium/high/xhigh/max) | thinking blocks, separate; adapter extracts text blocks only | thinking must be ACTIVATED on Opus (omitted = no thinking); adapter extended 2026-07-21 to send `thinking` + `output_config.effort` (direct AND batch path identical) |
| `claude_fable_5` | `effort` | `medium` | partially (depth via effort; thinking itself cannot be disabled) | thinking blocks (omitted by default), separate | always-on thinking needs no activation field; SAME effort level as the Opus pair partner |
| `qwen37_max` | `enable_thinking` + `thinking_budget` | ON, budget 8192 | partially (on/off + token budget; NO level scale) | separate `reasoning_content` | budget chosen non-constraining (well above observed spend, below the 16384 output cap) — it must not become the limiting factor |
| `qwen3_coder_api` | — | none | no (non-thinking model; `enable_thinking` silently ignored) | none | DOCUMENTED EXCEPTION: the model has no thinking to configure |
| `qwen36_35b_a3b` | `enable_thinking` + `thinking_budget` | ON, budget 8192 | partially (on/off + budget) | separate `reasoning_content` | same as qwen37_max |
| `deepseek_v4_pro` | `enable_thinking` + `reasoning_effort` | ON, `high` | partially (on/off + effort; effective levels high/max) | separate `reasoning_content` | `high` = LOWEST practically effective level of the DeepSeek scale — `medium` would be a de-facto throttle, so "middle" is not the faithful policy mapping here |
| `deepseek_v4_flash` | `enable_thinking` + `reasoning_effort` | ON, `high` | partially | separate `reasoning_content` | same as v4_pro (size pair runs one setting) |

Probe evidence (2026-07-21; structure probes per DashScope model with
the FINAL parameter combinations — qwen with thinking_budget 8192,
deepseek with reasoning_effort high): no DashScope model ever emitted
inline `<think>` blocks in `message.content` — thinking always arrives
as a separate `reasoning_content` field, so the assembly cleaning is
unaffected and the openai_compatible adapter needs no change
(`_extract_text` reads `message.content` exclusively;
`reasoning_content` is discarded, reasoning token counts are logged via
`usage` in the generation records).

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
(gpt-5.5 vs gpt-5.6-sol, Opus 4.8 vs Fable 5, DeepSeek pro vs flash)
run pairwise-identical settings and stay internally consistent.
Additionally: pipeline artifacts produced BEFORE 2026-07-21 (e.g.
smoke_001) ran the DeepSeek models with thinking disabled and Claude
Opus 4.8 without thinking — results from those runs are not comparable
to post-policy runs on this axis.

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
