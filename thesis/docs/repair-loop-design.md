# Repair Loop Design — Conversational Feedback for Code Improvement

Status: design (not yet implemented)
Depends on: generation stage (generation.v2), assembly stage (assembly.v1),
static analysis stage and correctness test stage (both not yet implemented).

## Goal

After the initial generation, each failing sample gets up to
`max_iterations` (default 3) repair attempts. The feedback (compiler
errors, curated static-analysis findings, failed test cases) is sent in the
**same conversation** in which the model produced the original code, so the
model has full context of its own previous attempt.

## Conversation model

A conversation is a provider-agnostic message list:

```json
[
  {"role": "user",      "content": "<original generation prompt>"},
  {"role": "assistant", "content": "<raw_text of generation>"},
  {"role": "user",      "content": "<feedback message, iteration 1>"},
  {"role": "assistant", "content": "<raw_text of repair 1>"},
  ...
]
```

Decisions:

1. **The assistant turn is `raw_text`, not `cleaned_code`.** The
   conversation must reflect what the model actually said; cleaning is a
   pipeline concern and stays out of the dialogue.
2. **The system prompt is the same as in generation** (from config,
   single source of truth) and is passed via the provider's system
   mechanism, not as a message.
3. **Text-only history.** Thinking/reasoning blocks are not replayed.
   Anthropic recommends passing thinking blocks back unchanged on Fable 5;
   omitting them is valid but loses thinking continuity. This is a
   documented limitation, accepted for cross-provider comparability —
   GPT-5.5 and Gemini reasoning traces cannot be replayed either, so
   replaying them only for Claude would bias the comparison.

## Adapter extension

`ProviderAdapter.generate()` gets a multi-turn variant (or `generate()` is
changed to accept `messages: list[dict]`; generation then passes a
single-element list):

```python
def generate(self, client, model_config, generation_defaults,
             system_prompt, messages, retry_attempts, sleep_seconds)
             -> GenerationResult
```

Provider mapping:

| Provider          | Mapping                                            |
|-------------------|----------------------------------------------------|
| anthropic         | `messages=` as-is, `system=` separate              |
| gemini            | `contents=[Content(role='user'/'model', parts=…)]` |
| openai (Responses)| `input=[{role: system}, …messages]`                |
| openai-compatible | `messages=[{role: system}, …messages]`             |

## Feedback message construction

One template for **all** models (fairness requirement — the repair prompt
must be byte-identical across providers except for the embedded findings):

```
Your previous implementation has problems. Fix them and return the
complete corrected code.

## Compiler errors (gcc -Wall -Wextra)
<first N lines of stderr, deduplicated>

## Static analysis findings (blocking checks only)
- [clang-tidy] bugprone-…: <message> (generated-code.hpp:LINE)
- [cppcheck] …
<max K findings, sorted by severity>

## Failed correctness tests
- input: …  expected: …  got: …
<max M failures>

Rules:
- Return only the corrected C++ code, no explanations.
- Keep the required execution model (<serial|OpenMP|MPI>).
- Do not change the function signature.
```

Curation rules (methodology-relevant):

- **Parsed, not raw.** Each tool gets a parser that extracts
  (tool, check_id, severity, file, line, message). Raw sanitizer/MUST
  output is hundreds of lines of noise; feeding it would partly measure
  noise filtering instead of repair capability.
- **Only blocking findings** go into feedback (the curated check set:
  `bugprone-*`, `concurrency-*`, `clang-analyzer-*`, `mpi-*`; sanitizer
  races; MUST errors). Non-blocking findings are logged but not sent.
- **Line numbers are remapped** to the model's own code: the assembly
  stage knows at which line of generated-code.hpp the model body starts,
  so findings can reference the code the model sees.
- **Caps:** N=50 compiler lines, K=15 findings, M=10 test failures —
  recorded in config so they are reproducible.

## Loop control

```
state: sources from assembly stage
for iteration in 1..max_iterations:
    evaluate sample (compile → static analysis → tests, 5–10 runs)
    if blocking_findings == 0 and all test runs pass: break  (early exit)
    feedback = build_feedback(results)
    messages += [assistant: last_raw_text, user: feedback]
    result = adapter.generate(messages)
    re-assemble source from result.raw_text (same cleaning pipeline)
record: iterations_used, final_status
```

- Early exit is mandatory (avoids regressions through unnecessary
  "improvements" and saves API budget).
- A repair response that is truncated/refused counts as a failed
  iteration; the loop continues with the previous best source.
- Per-sample final classification:
  `clean_initial | repaired_iter_k | failed_after_max | error`.

## Storage (schema repair.v1)

`<intermediate_dir>/<run_id>/<model_id>/repair.jsonl`, one record per
iteration per sample:

```json
{
  "schema_version": "repair.v1",
  "sample_id": "…",
  "iteration": 1,
  "feedback": {"compiler": […], "static": […], "tests": […]},
  "messages_sent": [ …full conversation as sent… ],
  "result": { …same shape as generation.v2 output/status… },
  "evaluation_after": {"compile": true, "blocking_findings": 0, "tests_passed": "10/10"}
}
```

Full conversations are stored verbatim — disk is cheap, auditability for
the thesis is not.

## Cost and context estimate

Worst case per sample: 1 generation + 3 repairs, conversation grows by
(raw_text + feedback) per round. With ~16k max output and typical ParEval
prompt sizes the context stays far below model limits. Main cost driver is
output tokens of reasoning models; the early exit and the blocking-only
feedback keep iterations down.

## Open implementation order

1. Static-analysis stage with per-tool parsers (prerequisite).
2. Correctness stage pointed at assembled sources (adapt
   CppDriverWrapper to consume persisted generated-code.hpp).
3. Adapter `messages` extension (small, mechanical).
4. Repair runner (`thesis/repair/run_repair.py`) implementing the loop.
