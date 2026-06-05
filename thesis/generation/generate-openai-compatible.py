"""
OpenAI-compatible generation script for the thesis pipeline.

Use this for providers that expose an OpenAI-compatible Chat Completions API,
for example Qwen/DashScope, DeepSeek, OpenRouter, Fireworks, Ollama, or LM Studio.

Called by:
    thesis/generation/generate.py

Example:
    python thesis/generation/generate-openai-compatible.py ^
        --config thesis/config/config.yaml ^
        --profile smoke ^
        --model-id qwen3_coder_api

Expected config example:

models:
  - id: qwen3_coder_api
    enabled: true
    provider: openai_compatible
    model_name: qwen3-coder-plus
    base_url_env: QWEN_BASE_URL
    api_key_env: QWEN_API_KEY

  - id: deepseek_v4_pro
    enabled: true
    provider: openai_compatible
    model_name: deepseek-v4-pro
    base_url: "https://api.deepseek.com"
    api_key_env: DEEPSEEK_API_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI


REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402


DEFAULT_SYSTEM_PROMPT = """You are an expert C++ and parallel programming assistant.
Complete the given function according to the prompt.
Return only the generated C++ code needed to complete the function.
Do not include Markdown, explanations, or extra text.
Preserve the required execution model: Serial, OpenMP, or MPI.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate code with an OpenAI-compatible API provider."
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to thesis config YAML.",
    )

    parser.add_argument(
        "--profile",
        required=True,
        help="Profile name from config, e.g. smoke, pilot, full.",
    )

    parser.add_argument(
        "--model-id",
        required=True,
        help="Model id from config, e.g. qwen3_coder_api.",
    )

    parser.add_argument(
        "--restart",
        action="store_true",
        help="Delete existing generation output and start from scratch.",
    )

    return parser.parse_args()


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


def read_existing_sample_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()

    sample_ids: set[str] = set()

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            sample_id = item.get("sample_id")
            if sample_id:
                sample_ids.add(sample_id)

    return sample_ids


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


def get_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})

    if profile_name not in profiles:
        available = ", ".join(profiles.keys())
        raise KeyError(
            f"Profile '{profile_name}' not found. Available profiles: {available}"
        )

    return profiles[profile_name]


def get_model_config(config: dict[str, Any], model_id: str) -> dict[str, Any]:
    models = config.get("models", [])
    matches = [model for model in models if model.get("id") == model_id]

    if not matches:
        raise KeyError(f"Model id '{model_id}' not found in config.")

    if len(matches) > 1:
        raise ValueError(f"Model id '{model_id}' appears multiple times in config.")

    model = matches[0]

    if model.get("provider") != "openai_compatible":
        raise ValueError(
            f"Model '{model_id}' has provider '{model.get('provider')}', "
            "but generate-openai-compatible.py only supports provider 'openai_compatible'."
        )

    if not model.get("enabled", False):
        raise ValueError(f"Model '{model_id}' is not enabled in config.")

    if not model.get("base_url") and not model.get("base_url_env"):
        raise ValueError(
            f"Model '{model_id}' is missing required field 'base_url' or 'base_url_env'."
        )

    if not model.get("api_key_env"):
        raise ValueError(f"Model '{model_id}' is missing required field 'api_key_env'.")

    if not model.get("model_name"):
        raise ValueError(f"Model '{model_id}' is missing required field 'model_name'.")

    return model


def resolve_base_url(model_config: dict[str, Any]) -> str:
    if model_config.get("base_url"):
        return model_config["base_url"]

    base_url_env = model_config.get("base_url_env")

    if base_url_env:
        base_url = os.environ.get(base_url_env)

        if not base_url:
            raise EnvironmentError(
                f"Missing base URL environment variable '{base_url_env}' "
                f"for model '{model_config['id']}'."
            )

        return base_url

    raise ValueError(
        f"Model '{model_config['id']}' is missing 'base_url' or 'base_url_env'."
    )


def resolve_api_key(model_config: dict[str, Any]) -> str:
    api_key_env = model_config.get("api_key_env")

    if not api_key_env:
        raise ValueError(f"Model '{model_config['id']}' is missing 'api_key_env'.")

    api_key = os.environ.get(api_key_env)

    if not api_key:
        raise EnvironmentError(
            f"Missing API key environment variable '{api_key_env}' "
            f"for model '{model_config['id']}'."
        )

    return api_key


def get_config_value(
    model_config: dict[str, Any],
    generation_defaults: dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    """
    Model-specific values override global generation_defaults.
    """
    if key in model_config and model_config[key] is not None:
        return model_config[key]

    return generation_defaults.get(key, default)


def filter_prompts(
    prompts: list[dict[str, Any]],
    execution_models: list[str] | None,
    problem_types: list[str] | None,
    prompt_limit: int | None,
) -> list[dict[str, Any]]:
    filtered = prompts

    if execution_models:
        allowed_execution_models = set(execution_models)
        filtered = [
            prompt
            for prompt in filtered
            if prompt.get("parallelism_model") in allowed_execution_models
        ]

    if problem_types:
        allowed_problem_types = set(problem_types)
        filtered = [
            prompt
            for prompt in filtered
            if prompt.get("problem_type") in allowed_problem_types
        ]

    if prompt_limit is not None:
        filtered = filtered[: int(prompt_limit)]

    return filtered


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
    """
    Conservative first-pass cleaning.

    Raw output is always preserved. More aggressive code normalization should
    happen in a later pipeline step.
    """
    return remove_markdown_fence(raw_text)


def get_output_paths(
    config: dict[str, Any],
    profile: dict[str, Any],
    model_config: dict[str, Any],
) -> tuple[Path, Path]:
    run_id = profile["run_id"]
    model_id = model_config["id"]

    outputs = config.get("outputs", {})
    raw_dir = Path(outputs.get("raw_dir", "thesis/results/raw"))

    output_dir = raw_dir / run_id / model_id

    generations_path = output_dir / "generations.jsonl"
    summary_path = output_dir / "generation_summary.json"

    return generations_path, summary_path


def safe_model_dump(obj: Any) -> dict[str, Any] | str | None:
    if obj is None:
        return None

    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            return repr(obj)

    return repr(obj)


def extract_usage(response: Any) -> dict[str, Any] | str | None:
    usage = getattr(response, "usage", None)

    if usage is None:
        return None

    if hasattr(usage, "model_dump"):
        return usage.model_dump()

    if isinstance(usage, dict):
        return usage

    return repr(usage)


def extract_response_text(response: Any) -> str:
    choices = getattr(response, "choices", None)

    if not choices:
        raise RuntimeError("Response does not contain choices.")

    first_choice = choices[0]
    message = getattr(first_choice, "message", None)

    if message is None:
        raise RuntimeError("First choice does not contain a message.")

    content = getattr(message, "content", None)

    if isinstance(content, str) and content.strip():
        return content

    raise RuntimeError("Could not extract text from OpenAI-compatible response.")


def extract_finish_reason(response: Any) -> str | None:
    choices = getattr(response, "choices", None)

    if not choices:
        return None

    return getattr(choices[0], "finish_reason", None)


def call_openai_compatible_with_retries(
    client: OpenAI,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float | None,
    top_p: float | None,
    retry_attempts: int,
    sleep_seconds: float,
    extra_body: dict[str, Any] | None = None,
) -> Any:
    last_error: Exception | None = None

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]

    request_payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    if temperature is not None:
        request_payload["temperature"] = temperature

    if top_p is not None:
        request_payload["top_p"] = top_p

    if extra_body:
        request_payload["extra_body"] = extra_body

    for attempt in range(retry_attempts + 1):
        try:
            return client.chat.completions.create(**request_payload)
        except Exception as error:
            last_error = error

            if attempt >= retry_attempts:
                break

            wait_time = sleep_seconds if sleep_seconds > 0 else min(2 ** attempt, 10)
            print(
                f"OpenAI-compatible call failed on attempt "
                f"{attempt + 1}/{retry_attempts + 1}: {error}"
            )
            print(f"Retrying in {wait_time:.1f}s...")
            time.sleep(wait_time)

    assert last_error is not None
    raise last_error


def build_empty_record(
    run_id: str,
    model_config: dict[str, Any],
    base_url_source: str,
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
        "schema_version": "generation.v1",
        "run_id": run_id,
        "sample_id": sample_id,
        "created_at_utc": utc_now_iso(),
        "model": {
            "id": model_config["id"],
            "provider": model_config["provider"],
            "model_name": model_config["model_name"],
            "base_url_source": base_url_source,
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
            "max_output_tokens": generation_parameters.get("max_output_tokens"),
            "temperature": generation_parameters.get("temperature"),
            "top_p": generation_parameters.get("top_p"),
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
            "error_type": None,
            "error_message": None,
            "duration_seconds": None,
        },
    }


def main() -> None:
    args = parse_args()

    config_path = Path(args.config).resolve()
    config = load_config(config_path)

    profile = get_profile(config, args.profile)
    model_config = get_model_config(config, args.model_id)

    prompts_config = config.get("prompts", {})
    generation_defaults = config.get("generation_defaults", {})

    run_id = profile["run_id"]

    prompts_path = Path(prompts_config["path"])
    prompt_field = prompts_config.get("prompt_field", "prompt")
    execution_models = prompts_config.get("execution_models")
    problem_types = prompts_config.get("problem_types")

    prompt_limit = profile.get("prompt_limit")
    num_samples_per_prompt = int(profile.get("num_samples_per_prompt", 1))

    max_output_tokens = int(
        get_config_value(
            model_config=model_config,
            generation_defaults=generation_defaults,
            key="max_output_tokens",
            default=4096,
        )
    )

    retry_attempts = int(
        get_config_value(
            model_config=model_config,
            generation_defaults=generation_defaults,
            key="retry_attempts",
            default=2,
        )
    )

    sleep_seconds = float(
        get_config_value(
            model_config=model_config,
            generation_defaults=generation_defaults,
            key="sleep_seconds_between_requests",
            default=0.0,
        )
    )

    temperature_value = get_config_value(
        model_config=model_config,
        generation_defaults=generation_defaults,
        key="temperature",
        default=None,
    )

    top_p_value = get_config_value(
        model_config=model_config,
        generation_defaults=generation_defaults,
        key="top_p",
        default=None,
    )

    temperature = float(temperature_value) if temperature_value is not None else None
    top_p = float(top_p_value) if top_p_value is not None else None

    system_prompt = get_config_value(
        model_config=model_config,
        generation_defaults=generation_defaults,
        key="system_prompt",
        default=DEFAULT_SYSTEM_PROMPT,
    )

    extra_body = model_config.get("extra_body")

    api_key = resolve_api_key(model_config)
    base_url = resolve_base_url(model_config)
    base_url_source = model_config.get("base_url") or model_config.get("base_url_env")

    generations_path, summary_path = get_output_paths(
        config=config,
        profile=profile,
        model_config=model_config,
    )

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

    existing_sample_ids = read_existing_sample_ids(generations_path)

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    requested_count = len(prompts) * num_samples_per_prompt

    generation_parameters = {
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        "top_p": top_p,
    }

    summary: dict[str, Any] = {
        "schema_version": "generation_summary.v1",
        "run_id": run_id,
        "model_id": model_config["id"],
        "provider": "openai_compatible",
        "model_name": model_config["model_name"],
        "base_url_source": base_url_source,
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
            "error": 0,
            "skipped_existing": 0,
        },
    }

    print("OpenAI-compatible generation")
    print("============================")
    print(f"Run ID:          {run_id}")
    print(f"Model ID:        {model_config['id']}")
    print(f"Model:           {model_config['model_name']}")
    print(f"Base URL source: {base_url_source}")
    print(f"Prompts:         {len(prompts)}")
    print(f"Samples:         {num_samples_per_prompt} per prompt")
    print(f"Output:          {generations_path}")
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
                base_url_source=base_url_source,
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

            try:
                response = call_openai_compatible_with_retries(
                    client=client,
                    model_name=model_config["model_name"],
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_output_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    retry_attempts=retry_attempts,
                    sleep_seconds=sleep_seconds,
                    extra_body=extra_body,
                )

                raw_text = extract_response_text(response)
                cleaned_code = clean_generated_code(raw_text)

                record["output"]["raw_text"] = raw_text
                record["output"]["cleaned_code"] = cleaned_code
                record["output"]["finish_reason"] = extract_finish_reason(response)
                record["api_response"]["response_id"] = getattr(response, "id", None)
                record["api_response"]["usage"] = extract_usage(response)
                record["api_response"]["raw_response_debug"] = None

                record["status"]["success"] = True
                summary["counts"]["success"] += 1

            except Exception as error:
                record["status"]["success"] = False
                record["status"]["error_type"] = type(error).__name__
                record["status"]["error_message"] = str(error)

                if "response" in locals():
                    record["api_response"]["raw_response_debug"] = safe_model_dump(
                        locals().get("response")
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
                f"{'success' if record['status']['success'] else 'error'}"
            )

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    summary["finished_at_utc"] = utc_now_iso()
    write_json(summary_path, summary)

    print()
    print("Finished OpenAI-compatible generation.")
    print(f"Success:          {summary['counts']['success']}")
    print(f"Errors:           {summary['counts']['error']}")
    print(f"Skipped existing: {summary['counts']['skipped_existing']}")
    print(f"Summary:          {summary_path}")


if __name__ == "__main__":
    main()