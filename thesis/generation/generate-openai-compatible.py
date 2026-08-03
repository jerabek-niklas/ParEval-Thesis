"""OpenAI-compatible generation script (Qwen, DeepSeek, ...) for the thesis pipeline.

Called by:
    thesis/generation/generate.py

Example:
    python thesis/generation/generate-openai-compatible.py --config thesis/config/config.yaml --profile smoke --model-id qwen3_coder_api

Notes:
    Uses the Chat Completions API against a configurable base_url
    (model_config.base_url or the env var named in model_config.base_url_env).
    Provider-specific options go through model_config.extra_body.

    Usage fields (persisted verbatim in api_response.usage): prompt_tokens,
    completion_tokens; reasoning tokens live in
    `completion_tokens_details.reasoning_tokens` (DashScope; verified live
    for the four thinking models in model-set.md's probe table). On
    non-thinking models (qwen3-coder-plus) `completion_tokens_details` is
    null — usage_normalized.reasoning_tokens is then None, which is
    correct: the model has nothing to report, the parameter is not being
    ignored. The separate `reasoning_content` text is NOT persisted (the
    adapter reads message.content only); its token count is what
    reasoning_tokens already measures.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import common  # noqa: E402


def resolve_base_url(model_config: dict[str, Any]) -> str:
    base_url = model_config.get("base_url")

    if base_url:
        return base_url

    base_url_env = model_config.get("base_url_env")

    if base_url_env:
        base_url = os.environ.get(base_url_env)

        if not base_url:
            raise EnvironmentError(
                f"Missing base URL environment variable '{base_url_env}' "
                f"for model '{model_config['id']}'."
            )

        return base_url

    raise KeyError(
        f"Model '{model_config['id']}' needs either 'base_url' or "
        f"'base_url_env' in the config."
    )


class OpenAICompatibleAdapter:
    provider = "openai_compatible"
    default_api_key_env = "OPENAI_COMPATIBLE_API_KEY"

    def create_client(
        self,
        model_config: dict[str, Any],
        api_key: str,
        timeout_seconds: float | None = None,
    ) -> OpenAI:
        # The SDK default is 600 s; generation_defaults.timeout_seconds wins.
        return OpenAI(
            api_key=api_key,
            base_url=resolve_base_url(model_config),
            timeout=timeout_seconds or common.DEFAULT_TIMEOUT_SECONDS,
        )

    def generation_parameters(
        self,
        model_config: dict[str, Any],
        generation_defaults: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "max_output_tokens": common.get_param(
                model_config, generation_defaults, "max_output_tokens", 4096
            ),
            "temperature": common.get_param(
                model_config, generation_defaults, "temperature"
            ),
            "top_p": common.get_param(model_config, generation_defaults, "top_p"),
            "extra_body": model_config.get("extra_body"),
        }

    def generate(
        self,
        client: OpenAI,
        model_config: dict[str, Any],
        generation_defaults: dict[str, Any],
        system_prompt: str,
        messages: list[dict[str, str]],
        retry_attempts: int,
        sleep_seconds: float,
    ) -> common.GenerationResult:
        params = self.generation_parameters(model_config, generation_defaults)

        request_payload: dict[str, Any] = {
            "model": model_config["model_name"],
            "messages": [
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            "max_tokens": int(params["max_output_tokens"]),
        }

        if params["temperature"] is not None:
            request_payload["temperature"] = float(params["temperature"])

        if params["top_p"] is not None:
            request_payload["top_p"] = float(params["top_p"])

        if params["extra_body"]:
            request_payload["extra_body"] = params["extra_body"]

        response = common.call_with_retries(
            fn=lambda: client.chat.completions.create(**request_payload),
            retry_attempts=retry_attempts,
            sleep_seconds=sleep_seconds,
            label="OpenAI-compatible",
        )

        finish_reason = self._extract_finish_reason(response)

        try:
            raw_text = self._extract_text(response)
        except Exception as error:
            error.raw_response = response  # type: ignore[attr-defined]
            raise

        return common.GenerationResult(
            raw_text=raw_text,
            finish_reason=finish_reason,
            truncated=finish_reason == "length",
            response_id=getattr(response, "id", None),
            usage=common.safe_model_dump(getattr(response, "usage", None)),
        )

    @staticmethod
    def _extract_finish_reason(response: Any) -> str | None:
        choices = getattr(response, "choices", None)

        if not choices:
            return None

        return getattr(choices[0], "finish_reason", None)

    @staticmethod
    def _extract_text(response: Any) -> str:
        choices = getattr(response, "choices", None)

        if not choices:
            raise RuntimeError("Response does not contain choices.")

        message = getattr(choices[0], "message", None)

        if message is None:
            raise RuntimeError("First choice does not contain a message.")

        content = getattr(message, "content", None)

        if isinstance(content, str) and content.strip():
            return content

        raise RuntimeError("Could not extract text from OpenAI-compatible response.")


if __name__ == "__main__":
    common.run_generation(OpenAICompatibleAdapter())
