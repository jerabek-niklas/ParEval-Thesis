"""Google Gemini generation script for the thesis pipeline.

Called by:
    thesis/generation/generate.py

Example:
    python thesis/generation/generate-gemini.py --config thesis/config/config.yaml --profile smoke --model-id gemini_31_pro
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import common  # noqa: E402


class GeminiAdapter:
    provider = "gemini"
    default_api_key_env = "GEMINI_API_KEY"

    def create_client(self, model_config: dict[str, Any], api_key: str) -> genai.Client:
        return genai.Client(api_key=api_key)

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
            "thinking_level": model_config.get("thinking_level"),
        }

    def generate(
        self,
        client: genai.Client,
        model_config: dict[str, Any],
        generation_defaults: dict[str, Any],
        system_prompt: str,
        messages: list[dict[str, str]],
        retry_attempts: int,
        sleep_seconds: float,
    ) -> common.GenerationResult:
        params = self.generation_parameters(model_config, generation_defaults)

        config_payload: dict[str, Any] = {
            "system_instruction": system_prompt,
            "max_output_tokens": int(params["max_output_tokens"]),
        }

        if params["temperature"] is not None:
            config_payload["temperature"] = float(params["temperature"])

        if params["top_p"] is not None:
            config_payload["top_p"] = float(params["top_p"])

        if params["thinking_level"] is not None:
            config_payload["thinking_config"] = types.ThinkingConfig(
                thinking_level=params["thinking_level"]
            )

        generation_config = types.GenerateContentConfig(**config_payload)

        contents = [
            types.Content(
                role="model" if message["role"] == "assistant" else "user",
                parts=[types.Part(text=message["content"])],
            )
            for message in messages
        ]

        response = common.call_with_retries(
            fn=lambda: client.models.generate_content(
                model=model_config["model_name"],
                contents=contents,
                config=generation_config,
            ),
            retry_attempts=retry_attempts,
            sleep_seconds=sleep_seconds,
            label="Gemini",
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
            truncated=finish_reason is not None and "MAX_TOKENS" in finish_reason,
            response_id=getattr(response, "response_id", None),
            usage=common.safe_model_dump(getattr(response, "usage_metadata", None)),
        )

    @staticmethod
    def _extract_finish_reason(response: Any) -> str | None:
        candidates = getattr(response, "candidates", None)

        if not candidates:
            return None

        finish_reason = getattr(candidates[0], "finish_reason", None)

        if finish_reason is None:
            return None

        # Enum value like FinishReason.MAX_TOKENS or plain string.
        return getattr(finish_reason, "name", None) or str(finish_reason)

    @staticmethod
    def _extract_text(response: Any) -> str:
        text = getattr(response, "text", None)

        if isinstance(text, str) and text.strip():
            return text

        candidates = getattr(response, "candidates", None)

        if not candidates:
            raise RuntimeError("Gemini response contains neither text nor candidates.")

        texts: list[str] = []

        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) if content is not None else None

            if not parts:
                continue

            for part in parts:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text.strip():
                    texts.append(part_text)

        if not texts:
            raise RuntimeError("Could not extract text from Gemini response.")

        return "\n".join(texts)


if __name__ == "__main__":
    common.run_generation(GeminiAdapter())
