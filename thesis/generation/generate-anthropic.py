"""Anthropic Claude generation script for the thesis pipeline.

Called by:
    thesis/generation/generate.py

Example:
    python thesis/generation/generate-anthropic.py --config thesis/config/config.yaml --profile smoke --model-id claude_fable_5

Notes:
    - temperature/top_p/top_k are not supported on Opus 4.7+/Fable 5 and
      are never sent.
    - Thinking differs per model: on Claude Fable 5 adaptive thinking is
      ALWAYS ON and cannot be disabled; on Opus 4.8/4.7 a request WITHOUT
      a thinking parameter runs with thinking OFF — it must be activated
      explicitly via `thinking: adaptive` in the model config. Reasoning
      depth is steered via `effort` (output_config.effort: low | medium |
      high | xhigh | max) on both. Thinking tokens count toward
      max_tokens, so the budget must be generous.
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


VALID_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def thinking_payload(model_config: dict[str, Any]) -> dict[str, Any]:
    """Thinking/effort request fields from the model config.

    Config keys (also consumed by batch_api._anthropic_submit — direct and
    batch requests must be configured identically):
      thinking: adaptive   activates adaptive thinking. REQUIRED for
                           Opus 4.8/4.7 (omitting it runs without
                           thinking); redundant-but-valid on Fable 5
                           (always on).
      effort: <level>      output_config.effort (low|medium|high|xhigh|max)

    Unknown values fail loudly — a typo must not silently change the
    reasoning regime of a whole run.
    """
    payload: dict[str, Any] = {}

    thinking = model_config.get("thinking")
    if thinking is not None:
        if thinking != "adaptive":
            raise ValueError(
                f"model '{model_config.get('id')}': thinking must be "
                f"'adaptive' (got {thinking!r}); the 4.7+/5 API accepts no "
                "other activation mode"
            )
        payload["thinking"] = {"type": "adaptive"}

    effort = model_config.get("effort")
    if effort is not None:
        if effort not in VALID_EFFORT_LEVELS:
            raise ValueError(
                f"model '{model_config.get('id')}': effort must be one of "
                f"{VALID_EFFORT_LEVELS} (got {effort!r})"
            )
        payload["output_config"] = {"effort": effort}

    return payload


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
            # As actually sent (see thinking_payload): explicit adaptive
            # activation and/or output_config.effort from the model config.
            "thinking": model_config.get("thinking"),
            "effort": model_config.get("effort"),
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

        extra = thinking_payload(model_config)

        response = common.call_with_retries(
            fn=lambda: client.messages.create(
                model=model_config["model_name"],
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
                **extra,
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
