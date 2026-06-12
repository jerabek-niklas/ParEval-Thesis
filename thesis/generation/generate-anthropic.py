"""Anthropic Claude generation script for the thesis pipeline.

Called by:
    thesis/generation/generate.py

Example:
    python thesis/generation/generate-anthropic.py --config thesis/config/config.yaml --profile smoke --model-id claude_fable_5

Notes (Claude Fable 5):
    - temperature/top_p/top_k are not supported and are never sent.
    - Adaptive thinking is always on and cannot be disabled; thinking tokens
      count toward max_tokens, so the budget must be generous.
    - Refusals arrive as HTTP 200 with stop_reason == "refusal"; they are
      recorded as error_type "ModelRefusal", not as success or API error.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from anthropic import Anthropic

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import common  # noqa: E402


class AnthropicAdapter:
    provider = "anthropic"
    default_api_key_env = "ANTHROPIC_API_KEY"

    def create_client(self, model_config: dict[str, Any], api_key: str) -> Anthropic:
        return Anthropic(api_key=api_key)

    def generation_parameters(
        self,
        model_config: dict[str, Any],
        generation_defaults: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "max_output_tokens": common.get_param(
                model_config, generation_defaults, "max_output_tokens", 4096
            ),
            # Not supported on Claude Fable 5 / Opus 4.7+; never sent.
            "temperature": None,
            "top_p": None,
            "thinking": "adaptive (model default, cannot be disabled)",
        }

    def generate(
        self,
        client: Anthropic,
        model_config: dict[str, Any],
        generation_defaults: dict[str, Any],
        system_prompt: str,
        messages: list[dict[str, str]],
        retry_attempts: int,
        sleep_seconds: float,
    ) -> common.GenerationResult:
        max_tokens = int(
            common.get_param(
                model_config, generation_defaults, "max_output_tokens", 4096
            )
        )

        response = common.call_with_retries(
            fn=lambda: client.messages.create(
                model=model_config["model_name"],
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            ),
            retry_attempts=retry_attempts,
            sleep_seconds=sleep_seconds,
            label="Anthropic",
        )

        stop_reason = getattr(response, "stop_reason", None)

        if stop_reason == "refusal":
            stop_details = getattr(response, "stop_details", None)
            raise common.ModelRefusal(
                f"Model refused the request. stop_details: "
                f"{common.safe_model_dump(stop_details)}"
            )

        try:
            raw_text = self._extract_text(response)
        except Exception as error:
            error.raw_response = response  # type: ignore[attr-defined]
            raise

        return common.GenerationResult(
            raw_text=raw_text,
            finish_reason=stop_reason,
            truncated=stop_reason == "max_tokens",
            response_id=getattr(response, "id", None),
            usage=common.safe_model_dump(getattr(response, "usage", None)),
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        texts: list[str] = []

        for block in response.content:
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", None)
                if isinstance(text, str) and text.strip():
                    texts.append(text)

        if not texts:
            raise RuntimeError("Could not extract text from Anthropic response.")

        return "\n".join(texts)


if __name__ == "__main__":
    common.run_generation(AnthropicAdapter())
