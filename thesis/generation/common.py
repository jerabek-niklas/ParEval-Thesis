"""Shared functionality for the thesis generation pipeline.

All provider scripts (generate-anthropic.py, generate-gemini.py,
generate-openai.py, generate-openai-compatible.py) implement a small
ProviderAdapter and delegate everything else to run_generation() here.

Record schema: generation.v3
    Adds compared to v2 (all additive; v2 fields keep name and meaning):
        status.timing_mode             "direct" | "batch"
        status.batch_submitted_at_utc  batch records only
        status.batch_completed_at_utc  batch records only
        api_response.usage_normalized  provider-independent token view
    Timing semantics: in direct mode status.duration_seconds is the real
    request latency, as before. In batch mode duration_seconds is NULL —
    the measurable wall time (submit -> result) is dominated by the
    provider QUEUE (up to 24 h, load- and time-of-day-dependent), so it is
    neither a latency measure nor a model property; the two timestamps
    record it without pretending otherwise. Batch and direct durations must
    never be mixed in one evaluation (docs/timing-and-effort.md).
    v2 added compared to v1:
        output.finish_reason   provider-reported stop/finish reason
        status.truncated       True when generation hit the token limit

Two API modes (generation_defaults.api_mode):
    direct  one synchronous call per sample
    batch   one provider batch job per model — submit, exit, and write the
            records on a later `--poll` (batch_api.py, shared with the
            repair loop). ~50% cheaper at up to 24 h latency, which is what
            the full run's 1980 calls are about.

Both modes fill records through apply_success()/apply_failure(); there is
deliberately no second write routine, so cleaning, the truncated flag,
refusal handling and the resume rule cannot drift apart between them.
"""

from __future__ import annotations

import argparse
import json
import re
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

GENERATION_SCHEMA_VERSION = "generation.v3"
SUMMARY_SCHEMA_VERSION = "generation_summary.v1"


# ---------------------------------------------------------------------------
# Exceptions and result types
# ---------------------------------------------------------------------------


class ModelRefusal(Exception):
    """The model declined the request (e.g. stop_reason 'refusal').

    This is an API-level success but must not be counted as a usable
    generation, and it is distinct from transport/API errors.
    """


class ReasoningBudgetExhausted(Exception):
    """The model spent the ENTIRE completion budget on reasoning.

    Observed on DeepSeek V4 Pro (reasoning_effort high): finish_reason
    "length" with EMPTY message.content — all 16384 completion tokens were
    reasoning, the answer never started (smoke_002 combined_feedback
    iter1, sample deepseek_v4_pro__dense_la__00_dense_la_lu_decomp__
    serial__sample_0: 58K chars of reasoning_content for a 1.8K request).

    DETERMINISTIC for a given request — retrying reproduces it token for
    token (measured: 3 identical failures), so it is TERMINAL like
    ModelRefusal: the record is persisted with the diagnosis in
    error_message and is NOT dropped for retry on resume. The actual fix
    is bounding the reasoning budget in the model config.
    """


# Failures that are DETERMINISTIC for a given request: retrying reproduces
# the same outcome and only costs money. load_resume_state (initial
# generation) keeps these records instead of dropping them for retry.
DETERMINISTIC_ERROR_TYPES = ("ReasoningBudgetExhausted",)

# The repair orchestrator's terminal set is WIDER: a ModelRefusal of a
# repair request also ends the sample (as repair_unusable) — retrying
# refusals forever would stall the wave. The initial generation, by
# contrast, deliberately RETRIES refusals (pre-existing behavior: a fresh
# attempt at the same task prompt can pass).
TERMINAL_ERROR_TYPES = ("ModelRefusal",) + DETERMINISTIC_ERROR_TYPES


@dataclass
class GenerationResult:
    raw_text: str
    finish_reason: str | None
    truncated: bool
    response_id: str | None
    usage: dict[str, Any] | str | None


class ProviderAdapter(Protocol):
    """Interface each provider script implements."""

    provider: str
    default_api_key_env: str

    def create_client(
        self,
        model_config: dict[str, Any],
        api_key: str,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Build the SDK client.

        `timeout_seconds` is the per-request timeout from the config and must
        be handed to the SDK — see get_timeout_seconds() for why leaving it
        out is not an option. Optional so callers that do not resolve a
        config (tests, ad-hoc scripts) still work.
        """
        ...

    def generation_parameters(
        self,
        model_config: dict[str, Any],
        generation_defaults: dict[str, Any],
    ) -> dict[str, Any]:
        """Parameters as actually sent to the API, recorded per sample."""
        ...

    def generate(
        self,
        client: Any,
        model_config: dict[str, Any],
        generation_defaults: dict[str, Any],
        system_prompt: str,
        messages: list[dict[str, str]],
        retry_attempts: int,
        sleep_seconds: float,
    ) -> GenerationResult:
        """Run one model call on a conversation.

        messages is a provider-agnostic list of {"role": "user"|"assistant",
        "content": str}. Initial generation passes a single user message;
        the repair loop passes the growing conversation. The system prompt
        is supplied separately and mapped to the provider's mechanism.
        """
        ...


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(item, ensure_ascii=False) + "\n")


def load_resume_state(path: Path) -> set[str]:
    """Return sample_ids of terminal records; drop retryable failures.

    Records with status.success == True are done. Failed records are
    normally removed from the JSONL so a rerun retries them (without
    duplicate sample_ids — validate_generations.py enforces uniqueness);
    this includes ModelRefusal, which a fresh attempt can clear.
    EXCEPTION: failures whose error_type is in DETERMINISTIC_ERROR_TYPES
    are KEPT and count as existing — retrying them reproduces the failure
    token for token and only costs money; the record with its diagnosis
    stays in the JSONL.
    """
    if not path.exists():
        return set()

    successful_ids: set[str] = set()
    kept_lines: list[str] = []
    dropped_count = 0

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                dropped_count += 1
                continue

            sample_id = item.get("sample_id")
            status = item.get("status") or {}
            terminal = (
                status.get("success") is True
                or status.get("error_type") in DETERMINISTIC_ERROR_TYPES
            )

            if terminal and sample_id:
                successful_ids.add(sample_id)
                kept_lines.append(line if line.endswith("\n") else line + "\n")
            else:
                dropped_count += 1

    if dropped_count > 0:
        with path.open("w", encoding="utf-8") as file:
            file.writelines(kept_lines)

        print(
            f"Resume: dropped {dropped_count} failed/invalid record(s) "
            f"from {path} so they can be retried."
        )

    return successful_ids


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def get_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})

    if profile_name not in profiles:
        available = ", ".join(profiles.keys())
        raise KeyError(
            f"Profile '{profile_name}' not found. Available profiles: {available}"
        )

    return profiles[profile_name]


def get_model_config(
    config: dict[str, Any],
    model_id: str,
    expected_provider: str,
) -> dict[str, Any]:
    models = config.get("models", [])

    matches = [model for model in models if model.get("id") == model_id]

    if not matches:
        raise KeyError(f"Model id '{model_id}' not found in config.")

    if len(matches) > 1:
        raise ValueError(f"Model id '{model_id}' appears multiple times in config.")

    model = matches[0]
    provider = model.get("provider")

    if provider != expected_provider:
        raise ValueError(
            f"Model '{model_id}' has provider '{provider}', but this script "
            f"only supports provider '{expected_provider}'."
        )

    if not model.get("enabled", False):
        raise ValueError(f"Model '{model_id}' is not enabled in config.")

    return model


def get_param(
    model_config: dict[str, Any],
    generation_defaults: dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    """Model-specific values override global generation_defaults."""
    if key in model_config and model_config[key] is not None:
        return model_config[key]

    return generation_defaults.get(key, default)


# Fallback when the config carries no timeout_seconds. Deliberately not the
# SDK defaults: the OpenAI client defaults to 600 s, so a single hung request
# would stall a run for ten minutes before the first retry.
DEFAULT_TIMEOUT_SECONDS = 120.0


def get_timeout_seconds(
    model_config: dict[str, Any],
    generation_defaults: dict[str, Any],
) -> float:
    """Per-request client timeout in seconds (model override > defaults).

    Every adapter must pass this into its SDK client. Without it the SDK
    default applies (OpenAI 600 s, Anthropic 600 s), which turns one hung
    request into a ten-minute stall — and with retries into half an hour.
    A timeout raises a retryable transport error, so call_with_retries()
    retries it like any other connection failure instead of losing the
    sample.
    """
    value = get_param(
        model_config, generation_defaults, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS
    )

    timeout = float(value)

    if timeout <= 0:
        raise ValueError(
            "generation_defaults.timeout_seconds must be > 0 (got %r); use a "
            "large value rather than 0 to mean 'no timeout'." % value
        )

    return timeout


def get_required_system_prompt(generation_defaults: dict[str, Any]) -> str:
    """The system prompt lives in config.yaml only (single source of truth)."""
    system_prompt = generation_defaults.get("system_prompt")

    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise KeyError(
            "generation_defaults.system_prompt is missing or empty in the "
            "config. It must be defined there (single source of truth)."
        )

    return system_prompt


def get_api_key(model_config: dict[str, Any], default_env: str) -> str:
    api_key_env = model_config.get("api_key_env", default_env)
    api_key = os.environ.get(api_key_env)

    if not api_key:
        raise EnvironmentError(
            f"Missing API key environment variable '{api_key_env}' "
            f"for model '{model_config['id']}'."
        )

    return api_key


def get_output_paths(
    config: dict[str, Any],
    profile: dict[str, Any],
    model_config: dict[str, Any],
) -> tuple[Path, Path]:
    run_id = profile["run_id"]
    model_id = model_config["id"]

    outputs = config.get("outputs", {})
    raw_dir = Path(outputs["raw_dir"])

    output_dir = raw_dir / run_id / model_id

    return output_dir / "generations.jsonl", output_dir / "generation_summary.json"


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def filter_prompts(
    prompts: list[dict[str, Any]],
    execution_models: list[str] | None,
    problem_types: list[str] | None,
    prompt_limit: int | None,
) -> list[dict[str, Any]]:
    filtered = prompts

    if execution_models:
        allowed = set(execution_models)
        filtered = [p for p in filtered if p.get("parallelism_model") in allowed]

    if problem_types:
        allowed = set(problem_types)
        filtered = [p for p in filtered if p.get("problem_type") in allowed]

    if prompt_limit is not None:
        filtered = filtered[: int(prompt_limit)]

    return filtered


PROMPT_SELECTIONS = ("prefix", "stratified")


def select_prompts(
    prompts: list[dict[str, Any]],
    execution_models: list[str] | None,
    problem_types: list[str] | None,
    prompt_limit: int | None,
    selection: str = "prefix",
) -> "tuple[list[dict[str, Any]], list[str]]":
    """THE prompt-selection function — used by BOTH the generation path
    and validate_generations.compute_expected_count, so the expected and
    actual sample counts agree by construction (two drifting copies would
    train everyone to ignore the validation warning).

    Returns (selected prompts, info lines to print).

    selection="prefix" (default): today's behavior byte-for-byte — a plain
    prefix of the benchmark-ordered prompt file. Small limits deliberately
    keep hitting the same benchmark as before (smoke/model_check/
    repair_smoke stay comparable across runs).

    selection="stratified": deterministic round-robin over problem_type.
    The unit of selection is the BENCHMARK, never the single prompt: every
    selected benchmark contributes ALL configured execution models,
    otherwise the sample would be skewed (e.g. serial-heavy) and the
    execution-model axis of the evaluation unbalanced. Benchmarks are
    sorted by (problem_type, benchmark_name) and the problem types walked
    round-robin, within a type in name order — no randomness, no shuffle:
    the same config always yields the same selection. NOTE: the name
    order within a problem type is NOT sorted by difficulty (checked:
    search 35 is harder than 36, reduce 26 harder than 27), so "first
    benchmark per type" is unbiased with respect to difficulty — do not
    "improve" this ordering later. prompt_limit stays a PROMPT count;
    whole benchmarks are taken until the limit is reached. A limit that
    is not a multiple of the active execution models rounds DOWN to the
    last complete benchmark (INFO line with the effective count) — a
    benchmark is never half-included.

    Subset property: with prompt_limit None ALL prompts are selected, so
    any limited selection is a SUBSET of the full run's — the
    precondition for later growing a pilot into the full run under the
    SAME run_id (resume adds only the missing samples). This holds only
    while the configuration in between stays unchanged (the run manifest
    records drift).
    """
    if selection not in PROMPT_SELECTIONS:
        raise ValueError(
            "profile selection must be one of %s (got %r)"
            % ("/".join(PROMPT_SELECTIONS), selection)
        )

    filtered = filter_prompts(prompts, execution_models, problem_types, None)

    if selection == "prefix":
        if prompt_limit is not None:
            filtered = filtered[: int(prompt_limit)]
        return filtered, []

    # ---- stratified ----------------------------------------------------
    by_benchmark: "dict[tuple[str, str], list[dict[str, Any]]]" = {}
    for prompt in filtered:
        key = (
            str(prompt.get("problem_type", "")),
            str(prompt.get("name", "")),
        )
        by_benchmark.setdefault(key, []).append(prompt)

    by_type: "dict[str, list[tuple[str, str]]]" = {}
    for key in sorted(by_benchmark):
        by_type.setdefault(key[0], []).append(key)

    types = sorted(by_type)

    # round-robin: round r takes the r-th benchmark of every type that
    # still has one
    benchmark_order: "list[tuple[str, str]]" = []
    max_rounds = max((len(v) for v in by_type.values()), default=0)
    for round_index in range(max_rounds):
        for problem_type in types:
            benchmarks = by_type[problem_type]
            if round_index < len(benchmarks):
                benchmark_order.append(benchmarks[round_index])

    limit = None if prompt_limit is None else int(prompt_limit)
    selected: "list[dict[str, Any]]" = []
    notes: "list[str]" = []
    truncated = False

    for key in benchmark_order:
        block = by_benchmark[key]
        if limit is not None and len(selected) + len(block) > limit:
            truncated = True
            break
        selected.extend(block)

    # only on a genuine round-down (a block did not fit) — a prompt pool
    # smaller than the limit is exhaustion, not rounding
    if truncated and len(selected) < (limit or 0):
        notes.append(
            "INFO: prompt_limit %d is not a multiple of the benchmark "
            "block size — rounded DOWN to %d prompts (%d complete "
            "benchmarks); a benchmark is never half-included."
            % (limit, len(selected),
               len({(p.get("problem_type"), p.get("name")) for p in selected}))
        )

    return selected, notes


def prompt_selection_report(
    selected: list[dict[str, Any]],
    selection: str,
    notes: list[str],
) -> "tuple[dict[str, Any], list[str]]":
    """(manifest block, console lines) describing the EFFECTIVE selection.

    Per selected benchmark the enhanced capability from
    benchmark_shapes.json is included (fill_sites,
    explicit_values_supported): "first benchmark per problem type" hits
    structural specials — e.g. 25_reduce_* with fill_sites 0 (no enhanced
    coverage at all) and 40_sort_* with explicit_values disabled. That is
    a legitimate property of the suite and must NOT be "fixed" by
    reordering (which would bias the pilot toward enhanced-friendly
    tasks) — it only has to be VISIBLE before the run instead of
    surfacing afterwards as a supposed bug in the evaluation.
    """
    from thesis.enhanced_tests.specs import benchmark_shape

    benchmarks: "list[dict[str, Any]]" = []
    seen: "dict[tuple[str, str], dict[str, Any]]" = {}

    for prompt in selected:
        key = (str(prompt.get("problem_type", "")), str(prompt.get("name", "")))
        entry = seen.get(key)
        if entry is None:
            shape = benchmark_shape("%s/%s" % key)
            entry = {
                "problem_type": key[0],
                "name": key[1],
                "execution_models": [],
                "fill_sites": shape.get("fill_sites"),
                "explicit_values_supported": bool(
                    shape.get("explicit_values_supported")
                ),
            }
            seen[key] = entry
            benchmarks.append(entry)
        entry["execution_models"].append(prompt.get("parallelism_model"))

    problem_types = sorted({b["problem_type"] for b in benchmarks})
    no_fill_site = [b for b in benchmarks if not b.get("fill_sites")]

    header = (
        "selection=%s, %d Benchmarks über %d Problemtypen, %d Prompts"
        % (selection, len(benchmarks), len(problem_types), len(selected))
    )

    lines = list(notes)
    lines.append(header)
    for bench in benchmarks:
        lines.append(
            "  %s/%s [%s] fill_sites=%s explicit_values=%s"
            % (
                bench["problem_type"], bench["name"],
                "/".join(bench["execution_models"]),
                bench["fill_sites"],
                "yes" if bench["explicit_values_supported"] else "no",
            )
        )
    lines.append(
        "%d von %d gewählten Benchmarks ohne ENHANCED_FILL-Site "
        "(Enhanced trägt dort nichts bei)"
        % (len(no_fill_site), len(benchmarks))
    )

    manifest_block = {
        "selection": selection,
        "header": header,
        "benchmarks": benchmarks,
        "benchmarks_without_fill_site": [
            "%s/%s" % (b["problem_type"], b["name"]) for b in no_fill_site
        ],
        "notes": list(notes),
    }

    return manifest_block, lines


def sanitize_for_id(value: Any) -> str:
    text = str(value)
    text = text.replace("/", "_").replace("\\", "_")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def make_sample_id(model_id: str, prompt: dict[str, Any], sample_index: int) -> str:
    return "__".join(
        [
            sanitize_for_id(model_id),
            sanitize_for_id(prompt.get("problem_type", "unknown_problem_type")),
            sanitize_for_id(prompt.get("name", "unknown_name")),
            sanitize_for_id(prompt.get("parallelism_model", "unknown_model")),
            f"sample_{sample_index}",
        ]
    )


def clean_generated_code(raw_text: str) -> str:
    """Informational quick clean stored in generation records.

    Delegates to the single cleaning implementation. The authoritative,
    prompt-aware cleaning happens in thesis/assembly/assemble_sources.py,
    which re-derives everything from raw_text.
    """
    from thesis.assembly.cleaning import extract_code

    return extract_code(raw_text)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def safe_model_dump(obj: Any) -> dict[str, Any] | str | None:
    if obj is None:
        return None

    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            return repr(obj)

    return repr(obj)


def call_with_retries(
    fn: Callable[[], Any],
    retry_attempts: int,
    sleep_seconds: float,
    label: str,
) -> Any:
    """Retry a transport-level API call with exponential backoff.

    Catches Exception, so a client timeout (openai.APITimeoutError /
    anthropic.APITimeoutError, both subclasses of the SDKs' connection
    errors, and httpx.TimeoutException underneath Gemini) is retried like
    any other transport failure. That is the intended behavior: a timeout
    should cost one retry, not the sample.
    """
    last_error: Exception | None = None

    for attempt in range(retry_attempts + 1):
        try:
            return fn()
        except Exception as error:
            last_error = error

            if attempt >= retry_attempts:
                break

            wait_time = sleep_seconds if sleep_seconds > 0 else min(2**attempt, 10)
            print(
                f"{label} call failed on attempt "
                f"{attempt + 1}/{retry_attempts + 1}: {error}"
            )
            print(f"Retrying in {wait_time:.1f}s...")
            time.sleep(wait_time)

    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------


def build_empty_record(
    run_id: str,
    model_config: dict[str, Any],
    prompt: dict[str, Any],
    prompt_field: str,
    sample_index: int,
    generation_parameters: dict[str, Any],
) -> dict[str, Any]:
    sample_id = make_sample_id(
        model_id=model_config["id"],
        prompt=prompt,
        sample_index=sample_index,
    )

    return {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "run_id": run_id,
        "sample_id": sample_id,
        "created_at_utc": utc_now_iso(),
        "model": {
            "id": model_config["id"],
            "provider": model_config["provider"],
            "model_name": model_config["model_name"],
        },
        "prompt": {
            "problem_type": prompt.get("problem_type"),
            "name": prompt.get("name"),
            "language": prompt.get("language"),
            "parallelism_model": prompt.get("parallelism_model"),
            "prompt_field": prompt_field,
            "prompt_text": prompt.get(prompt_field),
        },
        "generation_parameters": {
            "sample_index": sample_index,
            **generation_parameters,
        },
        "output": {
            "raw_text": None,
            "cleaned_code": None,
            "finish_reason": None,
        },
        "api_response": {
            "response_id": None,
            "usage": None,
            "usage_normalized": None,
            "raw_response_debug": None,
        },
        "status": {
            "success": False,
            "truncated": False,
            "error_type": None,
            "error_message": None,
            "duration_seconds": None,
            # "direct" | "batch", set by apply_direct_timing /
            # apply_batch_timing before the record is written
            "timing_mode": None,
        },
    }


def apply_direct_timing(record: dict[str, Any], started_at: float) -> None:
    """Direct mode: duration_seconds is the real request latency."""
    record["status"]["timing_mode"] = "direct"
    record["status"]["duration_seconds"] = round(time.time() - started_at, 3)


def apply_batch_timing(
    record: dict[str, Any],
    submitted_at_utc: str | None,
    completed_at_utc: str | None,
) -> None:
    """Batch mode: duration_seconds stays NULL, deliberately.

    The measurable wall time (submit -> completed poll) is dominated by the
    provider's batch QUEUE — up to 24 h, depending on load and time of day —
    and says nothing about the model; the batch APIs do not expose the
    actual per-request inference time. Writing the wall time into
    duration_seconds would let it masquerade as latency in any evaluation
    that aggregates the column, so the field stays None (not 0) and the
    span is recorded as two timestamps that cannot be mistaken for a
    latency measure.
    """
    record["status"]["timing_mode"] = "batch"
    record["status"]["duration_seconds"] = None
    record["status"]["batch_submitted_at_utc"] = submitted_at_utc
    record["status"]["batch_completed_at_utc"] = completed_at_utc


# Which usage field carries the reasoning tokens, per provider — measured
# per-model in thesis/docs/model-set.md ("thinking effectiveness probe"):
#   openai             usage.output_tokens_details.reasoning_tokens
#   anthropic          usage.output_tokens_details.thinking_tokens
#   gemini             usage_metadata.thoughts_token_count
#   openai_compatible  usage.completion_tokens_details.reasoning_tokens
#                      (DashScope; null on non-thinking models such as
#                      qwen3-coder-plus)
# Input/output counts per provider: input_tokens/output_tokens (openai,
# anthropic), prompt_token_count/candidates_token_count (gemini),
# prompt_tokens/completion_tokens (openai_compatible).
_REASONING_DETAIL_FIELDS = (
    ("output_tokens_details", "reasoning_tokens"),   # OpenAI Responses API
    ("output_tokens_details", "thinking_tokens"),    # Anthropic
    ("completion_tokens_details", "reasoning_tokens"),  # DashScope chat
)

_INPUT_TOKEN_KEYS = ("input_tokens", "prompt_tokens", "prompt_token_count")
_OUTPUT_TOKEN_KEYS = ("output_tokens", "completion_tokens", "candidates_token_count")


def normalize_usage(usage: Any) -> dict[str, Any] | None:
    """Provider-independent token view: input/output/reasoning tokens.

    Complements the raw usage (which is always kept verbatim) so the
    evaluation does not need to know five provider formats. reasoning_tokens
    is None when the provider reports no reasoning-token field at all —
    distinct from an explicit 0, which providers with adaptive thinking
    legitimately report on easy tasks. Key sets cover all five formats in
    use; the field names are documented per adapter and in model-set.md.
    """
    if not isinstance(usage, dict):
        return None

    def first_int(keys: tuple) -> "int | None":
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    reasoning: int | None = None

    # Gemini reports it flat; the others nest it in a details dict.
    thoughts = usage.get("thoughts_token_count")
    if isinstance(thoughts, int) and not isinstance(thoughts, bool):
        reasoning = thoughts
    else:
        for container_key, detail_key in _REASONING_DETAIL_FIELDS:
            details = usage.get(container_key)
            if isinstance(details, dict):
                value = details.get(detail_key)
                if isinstance(value, int) and not isinstance(value, bool):
                    reasoning = value
                    break

    return {
        "input_tokens": first_int(_INPUT_TOKEN_KEYS),
        "output_tokens": first_int(_OUTPUT_TOKEN_KEYS),
        "reasoning_tokens": reasoning,
    }


def reasoning_expected(model_config: dict[str, Any] | None) -> bool:
    """Does the reasoning policy configure this model to think?

    Read from the model config (the single source of the policy):
    anthropic `thinking`/`effort`, openai `reasoning_effort`, gemini
    `thinking_level`, DashScope `extra_body.enable_thinking`.
    """
    if not model_config:
        return False

    if model_config.get("thinking") or model_config.get("effort"):
        return True

    if model_config.get("reasoning_effort") or model_config.get("thinking_level"):
        return True

    extra_body = model_config.get("extra_body") or {}
    return bool(isinstance(extra_body, dict) and extra_body.get("enable_thinking"))


def reasoning_evidence_warning(
    record: dict[str, Any], model_config: dict[str, Any] | None
) -> str | None:
    """Warning text when a model configured to think shows no reasoning.

    The RUNNING counterpart of the one-off thinking probes in model-set.md:
    every successful record is checked, so a provider silently dropping the
    thinking parameter mid-run cannot go unnoticed. Two distinct cases:
    a MISSING reasoning-token field suggests the parameter is being ignored
    (the actual red flag), while an explicit 0 can be legitimate adaptive
    behavior on easy tasks (documented for Anthropic in model-set.md).
    Returns the text instead of printing so callers control the log.
    """
    if not reasoning_expected(model_config):
        return None

    normalized = record.get("api_response", {}).get("usage_normalized") or {}
    reasoning = normalized.get("reasoning_tokens")

    sample_id = record.get("sample_id", "?")

    if reasoning is None:
        return (
            "WARNING [%s]: model is configured to think but the usage "
            "reports NO reasoning-token field — the thinking parameter may "
            "be ignored by the provider" % sample_id
        )

    if reasoning == 0:
        return (
            "WARNING [%s]: model is configured to think but spent 0 "
            "reasoning tokens (can be legitimate adaptive behavior on easy "
            "tasks; investigate if it happens across the whole run)"
            % sample_id
        )

    return None


def apply_success(
    record: dict[str, Any],
    summary: dict[str, Any],
    raw_text: str,
    finish_reason: str | None,
    truncated: bool,
    response_id: str | None,
    usage: Any,
    model_config: dict[str, Any] | None = None,
) -> str:
    """Fill a record from a successful generation and count it.

    THE single success path — direct mode and batch mode both go through
    it, so cleaning, the truncated flag and the summary counters can never
    drift apart between the two. Also derives usage_normalized from the
    raw usage and, when `model_config` is given, logs the ongoing
    reasoning-evidence check (see reasoning_evidence_warning).
    """
    record["output"]["raw_text"] = raw_text
    record["output"]["cleaned_code"] = clean_generated_code(raw_text)
    record["output"]["finish_reason"] = finish_reason
    record["api_response"]["response_id"] = response_id
    record["api_response"]["usage"] = usage
    record["api_response"]["usage_normalized"] = normalize_usage(usage)

    record["status"]["success"] = True
    record["status"]["truncated"] = truncated

    warning = reasoning_evidence_warning(record, model_config)
    if warning:
        print(warning)
        # ALSO persisted (generation_summary.json): a single stdout line
        # scrolls past unseen — smoke_004's 0-thinking warnings fired but
        # were only noticed via manual recomputation a day later. The
        # artifact makes the evidence reviewable after the run.
        summary.setdefault("reasoning_warnings", []).append(warning)

    summary["counts"]["success"] += 1

    if truncated:
        summary["counts"]["truncated"] += 1
        return "truncated"

    return "success"


def apply_failure(
    record: dict[str, Any],
    summary: dict[str, Any],
    error_type: str,
    error_message: str,
    raw_response_debug: Any = None,
) -> str:
    """Fill a record from a failed generation and count it (single path,
    see apply_success). ModelRefusal is a terminal, non-transport failure
    and is additionally counted as `refused`."""
    record["status"]["error_type"] = error_type
    record["status"]["error_message"] = error_message

    if raw_response_debug is not None:
        record["api_response"]["raw_response_debug"] = raw_response_debug

    summary["counts"]["error"] += 1

    if error_type == "ModelRefusal":
        record["output"]["finish_reason"] = "refusal"
        summary["counts"]["refused"] += 1
        return "refused"

    return "error"


def run_batch_stage(
    adapter: ProviderAdapter,
    model_config: dict[str, Any],
    generation_defaults: dict[str, Any],
    system_prompt: str,
    pending: list,
    summary: dict[str, Any],
    generations_path: Path,
    write_record: Callable[..., None],
    poll_only: bool,
) -> bool:
    """Submit / poll the model's batch job. Returns True when it finished.

    Two-step by design, exactly like the repair loop: the first invocation
    submits and exits (batch jobs run for minutes to hours — no process
    waits for them), a later invocation with --poll writes the results.
    The bookkeeping file next to generations.jsonl holds the job id and the
    ORDERED sample_ids, because the providers' custom ids are capped at 64
    characters and responses map back positionally.

    Results are written through the same write_record/apply_* path as
    direct mode; this function never touches record fields itself.
    """
    from thesis.generation import batch_api

    info_path = batch_info_path(generations_path)
    existing = read_json(info_path) if info_path.exists() else None

    # ---- submit ----------------------------------------------------------
    if existing is None:
        if poll_only:
            print("--poll: no submitted batch job found; nothing to do.")
            return False

        if not pending:
            print("Nothing pending — no batch submitted.")
            return True

        requests = [(record["sample_id"], user_prompt)
                    for _prompt, user_prompt, record in pending]

        batch_info = batch_api.submit_batch(
            provider=adapter.provider,
            model_config=model_config,
            generation_defaults=generation_defaults,
            system_prompt=system_prompt,
            requests=requests,
        )

        batch_info["sample_ids"] = [sample_id for sample_id, _text in requests]
        batch_info["submitted_at_utc"] = utc_now_iso()
        batch_info["provider"] = adapter.provider
        batch_info["model_id"] = model_config["id"]

        write_json(info_path, batch_info)

        print(
            "Batch submitted: %d request(s), job %s"
            % (len(requests), batch_info.get("batch_id"))
        )
        print("Bookkeeping:      %s" % info_path)
        print("Poll with:        --poll (same command, adds --poll)")

        return False

    # ---- poll ------------------------------------------------------------
    status = batch_api.poll_batch(
        provider=adapter.provider,
        model_config=model_config,
        batch_info=existing,
    )

    if status.state == "running":
        print(
            "Batch %s still running (%s) — re-run with --poll later."
            % (existing.get("batch_id"), status.detail)
        )
        return False

    if status.state == "failed":
        print(
            "Batch %s FAILED (%s). Delete %s to resubmit."
            % (existing.get("batch_id"), status.detail, info_path)
        )
        return False

    by_sample = {record["sample_id"]: (prompt, record)
                 for prompt, _user_prompt, record in pending}

    written = 0
    missing = []

    # One completion timestamp for the whole job: the API reports batch-level
    # completion only, and the span is a queue-time bound either way (see
    # apply_batch_timing), not a per-request measurement.
    completed_at_utc = utc_now_iso()

    for sample_id, item in status.responses.items():
        entry = by_sample.get(sample_id)

        if entry is None:
            # already written by an earlier poll (resume) or not requested
            continue

        prompt, record = entry

        if item.error_type:
            outcome = apply_failure(
                record, summary, item.error_type, item.error_message or ""
            )
        else:
            outcome = apply_success(
                record, summary,
                raw_text=item.raw_text or "",
                finish_reason=item.finish_reason,
                truncated=item.truncated,
                response_id=item.response_id,
                usage=item.usage,
                model_config=model_config,
            )

        apply_batch_timing(
            record,
            submitted_at_utc=existing.get("submitted_at_utc"),
            completed_at_utc=completed_at_utc,
        )
        write_record(prompt, record, outcome)
        written += 1

    for sample_id in by_sample:
        if sample_id not in status.responses:
            missing.append(sample_id)

    print()
    print("Batch %s completed: %d record(s) written."
          % (existing.get("batch_id"), written))

    if missing:
        # Not an error case to swallow: an unanswered request must stay
        # visible so a rerun (which resubmits only the missing samples)
        # picks it up.
        print(
            "WARNING: %d request(s) came back without a response and were "
            "NOT written: %s" % (len(missing), ", ".join(sorted(missing)[:5]))
        )

    # keep the job file for provenance; rename so a rerun submits afresh
    info_path.replace(info_path.with_suffix(".done.json"))

    return True


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def parse_args(provider: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Generate code with a {provider} model for thesis ParEval prompts."
    )

    parser.add_argument("--config", required=True, help="Path to thesis config YAML.")
    parser.add_argument(
        "--profile", required=True, help="Profile name, e.g. smoke, pilot, full."
    )
    parser.add_argument("--model-id", required=True, help="Model id from config.")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Delete existing generation output and start from scratch.",
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Batch mode only: check the submitted job and write the finished "
        "records; does not submit anything new.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Batch mode (api_mode: batch)
# ---------------------------------------------------------------------------

# Providers with a verified/implemented batch path. The openai_compatible
# endpoints (DashScope: Qwen, DeepSeek, GLM) have no /v1/batches — probed
# 2026-07-21, HTTP 404 — so they always run direct. Same list and same
# fallback behavior as the repair loop (orchestrator.BATCH_PROVIDERS).
BATCH_PROVIDERS = ("openai", "anthropic", "gemini")


def resolve_api_mode(
    generation_defaults: dict[str, Any], provider: str
) -> tuple[str, str | None]:
    """(effective mode, fallback note).

    generation_defaults.api_mode with a per-provider override; providers
    without a batch implementation fall back to direct with a note, exactly
    like the repair loop.
    """
    overrides = generation_defaults.get("api_mode_overrides") or {}
    requested = overrides.get(provider, generation_defaults.get("api_mode", "direct"))

    if requested not in ("direct", "batch"):
        raise ValueError(
            "generation_defaults.api_mode must be 'direct' or 'batch' "
            "(got %r)" % requested
        )

    if requested == "batch" and provider not in BATCH_PROVIDERS:
        return "direct", (
            "provider '%s' has no verified batch API (DashScope endpoints "
            "return 404 on /v1/batches) — falling back to direct" % provider
        )

    return requested, None


def batch_info_path(generations_path: Path) -> Path:
    """Batch bookkeeping next to the model's generations.jsonl."""
    return generations_path.parent / "generation_batch.json"


def run_generation(adapter: ProviderAdapter) -> None:
    # Imported lazily so common.py has no hard dependency on the repo layout.
    from thesis.config.load_config import load_config

    args = parse_args(adapter.provider)

    config_path = Path(args.config).resolve()
    config = load_config(config_path)

    profile = get_profile(config, args.profile)
    model_config = get_model_config(config, args.model_id, adapter.provider)

    prompts_config = config.get("prompts", {})
    generation_defaults = config.get("generation_defaults", {})

    run_id = profile["run_id"]

    prompts_path = Path(prompts_config["path"])
    prompt_field = prompts_config.get("prompt_field", "prompt")
    execution_models = prompts_config.get("execution_models")
    problem_types = prompts_config.get("problem_types")

    prompt_limit = profile.get("prompt_limit")
    num_samples_per_prompt = int(profile.get("num_samples_per_prompt", 1))

    retry_attempts = int(get_param(model_config, generation_defaults, "retry_attempts", 2))
    sleep_seconds = float(
        get_param(model_config, generation_defaults, "sleep_seconds_between_requests", 0.0)
    )
    system_prompt = get_required_system_prompt(generation_defaults)

    api_key = get_api_key(model_config, adapter.default_api_key_env)

    generations_path, summary_path = get_output_paths(config, profile, model_config)

    if args.restart and generations_path.exists():
        generations_path.unlink()

    prompts = read_json(prompts_path)

    if not isinstance(prompts, list):
        raise ValueError(f"Expected list in prompts JSON: {prompts_path}")

    prompts, selection_notes = select_prompts(
        prompts=prompts,
        execution_models=execution_models,
        problem_types=problem_types,
        prompt_limit=prompt_limit,
        selection=profile.get("selection", "prefix"),
    )
    for note in selection_notes:
        print(note)

    existing_sample_ids = load_resume_state(generations_path)

    timeout_seconds = get_timeout_seconds(model_config, generation_defaults)

    client = adapter.create_client(model_config, api_key, timeout_seconds)

    generation_parameters = adapter.generation_parameters(
        model_config, generation_defaults
    )

    requested_count = len(prompts) * num_samples_per_prompt

    summary: dict[str, Any] = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "run_id": run_id,
        "model_id": model_config["id"],
        "provider": adapter.provider,
        "model_name": model_config["model_name"],
        "created_at_utc": utc_now_iso(),
        "config_path": str(config_path),
        "prompts_path": str(prompts_path),
        "generations_path": str(generations_path),
        "num_prompts": len(prompts),
        "num_samples_per_prompt": num_samples_per_prompt,
        "generation_parameters": generation_parameters,
        "counts": {
            "requested": requested_count,
            "success": 0,
            "truncated": 0,
            "refused": 0,
            "error": 0,
            "skipped_existing": 0,
        },
    }

    api_mode, fallback_note = resolve_api_mode(generation_defaults, adapter.provider)
    summary["api_mode"] = api_mode

    print(f"{adapter.provider.capitalize()} generation")
    print("=" * 20)
    print(f"Run ID:    {run_id}")
    print(f"Model ID:  {model_config['id']}")
    print(f"Model:     {model_config['model_name']}")
    print(f"Prompts:   {len(prompts)}")
    print(f"Samples:   {num_samples_per_prompt} per prompt")
    print(f"API mode:  {api_mode}")
    print(f"Output:    {generations_path}")

    if fallback_note:
        print(f"NOTE:      {fallback_note}")

    print()

    # ---- pending work (identical in both modes; this is the resume rule) --
    pending: list[tuple[dict[str, Any], str, dict[str, Any]]] = []

    for prompt in prompts:
        if prompt_field not in prompt:
            raise KeyError(
                f"Prompt field '{prompt_field}' missing for "
                f"{prompt.get('name')} / {prompt.get('parallelism_model')}"
            )

        user_prompt = prompt[prompt_field]

        for sample_index in range(num_samples_per_prompt):
            record = build_empty_record(
                run_id=run_id,
                model_config=model_config,
                prompt=prompt,
                prompt_field=prompt_field,
                sample_index=sample_index,
                generation_parameters=generation_parameters,
            )

            if record["sample_id"] in existing_sample_ids:
                summary["counts"]["skipped_existing"] += 1
                continue

            pending.append((prompt, user_prompt, record))

    def write_record(prompt: dict[str, Any], record: dict[str, Any],
                     outcome: str) -> None:
        # timing is applied by the caller (apply_direct_timing /
        # apply_batch_timing) — the two modes measure different things
        append_jsonl(generations_path, record)

        done = (
            summary["counts"]["success"]
            + summary["counts"]["error"]
            + summary["counts"]["skipped_existing"]
        )

        print(
            f"[{done}/{requested_count}] "
            f"{prompt.get('problem_type')} | "
            f"{prompt.get('name')} | "
            f"{prompt.get('parallelism_model')} | "
            f"sample {record['generation_parameters']['sample_index']} | "
            f"{outcome}"
        )

    if api_mode == "batch":
        finished = run_batch_stage(
            adapter=adapter,
            model_config=model_config,
            generation_defaults=generation_defaults,
            system_prompt=system_prompt,
            pending=pending,
            summary=summary,
            generations_path=generations_path,
            write_record=write_record,
            poll_only=args.poll,
        )

        if not finished:
            # submitted (or still running): nothing more to do in this
            # process — the summary is written on the poll that completes it
            return
    else:
        if args.poll:
            print("--poll has no effect in direct mode; nothing to do.")
            return

        for prompt, user_prompt, record in pending:
            started_at = time.time()

            try:
                result = adapter.generate(
                    client=client,
                    model_config=model_config,
                    generation_defaults=generation_defaults,
                    system_prompt=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    retry_attempts=retry_attempts,
                    sleep_seconds=sleep_seconds,
                )

                outcome = apply_success(
                    record, summary,
                    raw_text=result.raw_text,
                    finish_reason=result.finish_reason,
                    truncated=result.truncated,
                    response_id=result.response_id,
                    usage=result.usage,
                    model_config=model_config,
                )

            except ModelRefusal as refusal:
                outcome = apply_failure(
                    record, summary, "ModelRefusal", str(refusal)
                )

            except Exception as error:
                outcome = apply_failure(
                    record, summary,
                    type(error).__name__,
                    str(error),
                    safe_model_dump(getattr(error, "raw_response", None)),
                )

            apply_direct_timing(record, started_at)
            write_record(prompt, record, outcome)

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    summary["finished_at_utc"] = utc_now_iso()
    write_json(summary_path, summary)

    print()
    print(f"Finished {adapter.provider} generation.")
    print(f"Success:          {summary['counts']['success']}")
    print(f"  thereof truncated: {summary['counts']['truncated']}")
    print(f"Refused:          {summary['counts']['refused']}")
    print(f"Errors:           {summary['counts']['error']}")
    print(f"Skipped existing: {summary['counts']['skipped_existing']}")
    print(f"Summary:          {summary_path}")
