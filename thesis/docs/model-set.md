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
| `openai_gpt56_sol` | `gpt-5.6-sol` | yes (smoke 2026-07-21 — no 403, so the gpt-5.6-terra fallback id was NOT needed) | yes (Batch API, implemented, not live-tested) | $5.00 / $30.00 | 2026-07-21 |
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
