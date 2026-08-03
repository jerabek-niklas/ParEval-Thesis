"""OpenAI generation script (Responses API) for the thesis pipeline.

Called by:
    thesis/generation/generate.py

Example:
    python thesis/generation/generate-openai.py --config thesis/config/config.yaml --profile smoke --model-id openai_gpt55

Notes:
    Reasoning models on the Responses API do not accept temperature/top_p,
    so they are never sent and recorded as None. Reasoning tokens count
    toward max_output_tokens; truncation is detected via response.status ==
    "incomplete" with incomplete_details.reason == "max_output_tokens".

    Usage fields (persisted verbatim in api_response.usage): input_tokens,
    output_tokens; reasoning tokens live in
    `output_tokens_details.reasoning_tokens` (always present on reasoning
    models — the source for usage_normalized.reasoning_tokens).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import common  # noqa: E402


class OpenAIAdapter:
    provider = "openai"
    default_api_key_env = "OPENAI_API_KEY"

    def create_client(
        self,
        model_config: dict[str, Any],
        api_key: str,
        timeout_seconds: float | None = None,
    ) -> OpenAI:
        # The SDK default is 600 s; generation_defaults.timeout_seconds wins.
        return OpenAI(
            api_key=api_key,
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
            # Reasoning models on the Responses API do not accept
            # temperature/top_p; never sent, recorded as None.
            "temperature": None,
            "top_p": None,
            "reasoning_effort": model_config.get("reasoning_effort"),
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

        payload: dict[str, Any] = {
            "model": model_config["model_name"],
            "input": [
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            "max_output_tokens": int(params["max_output_tokens"]),
        }

        if params["reasoning_effort"]:
            payload["reasoning"] = {"effort": params["reasoning_effort"]}

        response = common.call_with_retries(
            fn=lambda: client.responses.create(**payload),
            retry_attempts=retry_attempts,
            sleep_seconds=sleep_seconds,
            label="OpenAI",
        )

        finish_reason, truncated = self._extract_finish_state(response)

        try:
            raw_text = self._extract_text(response)
        except Exception as error:
            error.raw_response = response  # type: ignore[attr-defined]
            raise

        return common.GenerationResult(
            raw_text=raw_text,
            finish_reason=finish_reason,
            truncated=truncated,
            response_id=getattr(response, "id", None),
            usage=common.safe_model_dump(getattr(response, "usage", None)),
        )

    @staticmethod
    def _extract_finish_state(response: Any) -> tuple[str | None, bool]:
        status = getattr(response, "status", None)

        if status != "incomplete":
            return status, False

        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) if details is not None else None

        finish_reason = f"incomplete:{reason}" if reason else "incomplete"

        return finish_reason, reason == "max_output_tokens"

    @staticmethod
    def _extract_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)

        if output_text:
            return output_text

        output_items = getattr(response, "output", None)

        if not output_items:
            raise RuntimeError(
                "OpenAI response contains neither output_text nor output items."
            )

        texts: list[str] = []

        for item in output_items:
            content = getattr(item, "content", None)

            if not content:
                continue

            for part in content:
                text = getattr(part, "text", None)
                if text:
                    texts.append(text)

        if not texts:
            raise RuntimeError("Could not extract text from OpenAI response.")

        return "\n".join(texts)


if __name__ == "__main__":
    common.run_generation(OpenAIAdapter())
