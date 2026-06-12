"""Shared functionality for the thesis generation pipeline.

All provider scripts (generate-anthropic.py, generate-gemini.py,
generate-openai.py, generate-openai-compatible.py) implement a small
ProviderAdapter and delegate everything else to run_generation() here.

Record schema: generation.v2
    Adds compared to v1:
        output.finish_reason   provider-reported stop/finish reason
        status.truncated       True when generation hit the token limit
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

GENERATION_SCHEMA_VERSION = "generation.v2"
SUMMARY_SCHEMA_VERSION = "generation_summary.v1"


# ---------------------------------------------------------------------------
# Exceptions and result types
# ---------------------------------------------------------------------------


class ModelRefusal(Exception):
    """The model declined the request (e.g. stop_reason 'refusal').

    This is an API-level success but must not be counted as a usable
    generation, and it is distinct from transport/API errors.
    """


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

    def create_client(self, model_config: dict[str, Any], api_key: str) -> Any:
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
        user_prompt: str,
        retry_attempts: int,
        sleep_seconds: float,
    ) -> GenerationResult:
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
    """Return sample_ids of successful records; drop failed records for retry.

    Only records with status.success == True are treated as existing. Failed
    records are removed from the JSONL so that retried samples do not create
    duplicate sample_ids (validate_generations.py enforces uniqueness).
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
            success = (item.get("status") or {}).get("success") is True

            if success and sample_id:
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


def remove_markdown_fence(text: str) -> str:
    pattern = re.compile(
        r"```(?:cpp|c\+\+|cxx|C\+\+)?\s*(.*?)```",
        flags=re.DOTALL | re.IGNORECASE,
    )

    match = pattern.search(text)

    if match:
        return match.group(1).strip()

    return text.strip()


def clean_generated_code(raw_text: str) -> str:
    return remove_markdown_fence(raw_text)


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
    """Retry a transport-level API call with exponential backoff."""
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
            "raw_response_debug": None,
        },
        "status": {
            "success": False,
            "truncated": False,
            "error_type": None,
            "error_message": None,
            "duration_seconds": None,
        },
    }


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

    return parser.parse_args()


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

    prompts = filter_prompts(
        prompts=prompts,
        execution_models=execution_models,
        problem_types=problem_types,
        prompt_limit=prompt_limit,
    )

    existing_sample_ids = load_resume_state(generations_path)

    client = adapter.create_client(model_config, api_key)

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

    print(f"{adapter.provider.capitalize()} generation")
    print("=" * 20)
    print(f"Run ID:    {run_id}")
    print(f"Model ID:  {model_config['id']}")
    print(f"Model:     {model_config['model_name']}")
    print(f"Prompts:   {len(prompts)}")
    print(f"Samples:   {num_samples_per_prompt} per prompt")
    print(f"Output:    {generations_path}")
    print()

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

            sample_id = record["sample_id"]

            if sample_id in existing_sample_ids:
                summary["counts"]["skipped_existing"] += 1
                continue

            started_at = time.time()
            outcome = "error"

            try:
                result = adapter.generate(
                    client=client,
                    model_config=model_config,
                    generation_defaults=generation_defaults,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    retry_attempts=retry_attempts,
                    sleep_seconds=sleep_seconds,
                )

                record["output"]["raw_text"] = result.raw_text
                record["output"]["cleaned_code"] = clean_generated_code(result.raw_text)
                record["output"]["finish_reason"] = result.finish_reason
                record["api_response"]["response_id"] = result.response_id
                record["api_response"]["usage"] = result.usage

                record["status"]["success"] = True
                record["status"]["truncated"] = result.truncated

                if result.truncated:
                    summary["counts"]["truncated"] += 1
                    outcome = "truncated"
                else:
                    outcome = "success"

                summary["counts"]["success"] += 1

            except ModelRefusal as refusal:
                record["status"]["error_type"] = "ModelRefusal"
                record["status"]["error_message"] = str(refusal)
                record["output"]["finish_reason"] = "refusal"

                summary["counts"]["refused"] += 1
                summary["counts"]["error"] += 1
                outcome = "refused"

            except Exception as error:
                record["status"]["error_type"] = type(error).__name__
                record["status"]["error_message"] = str(error)
                record["api_response"]["raw_response_debug"] = safe_model_dump(
                    getattr(error, "raw_response", None)
                )

                summary["counts"]["error"] += 1

            record["status"]["duration_seconds"] = round(time.time() - started_at, 3)
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
                f"sample {sample_index} | "
                f"{outcome}"
            )

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
