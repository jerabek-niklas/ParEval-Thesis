"""Provider batch APIs for the repair loop (repair-loop-design.md §7).

One batch job per (model, variant, iteration); the orchestrator submits,
exits, and merges results on a later --poll / regular run. Payloads and
text extraction MIRROR the direct-mode provider adapters
(thesis/generation/generate-*.py) so batch and direct responses are
comparable records.

custom_id note: OpenAI and Anthropic cap custom ids at 64 characters,
which our sample_ids exceed. Requests therefore use positional ids
("req_<index>"); the orchestrator persists the ordered sample_id list in
batch.json, and index_to_sample below maps results back. Gemini's inline
batch has no custom ids at all — responses come back in request order,
which maps through the same list.

Only the submit/poll functions import the provider SDKs (lazily), so the
orchestrator and its tests never need them installed.

Python 3.8 compatible.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import common  # noqa: E402


@dataclass
class BatchItemResponse:
    """One sample's result out of a batch (mirrors GenerationResult plus
    error fields; error_type 'ModelRefusal' is terminal for the sample)."""

    raw_text: Optional[str] = None
    finish_reason: Optional[str] = None
    truncated: bool = False
    response_id: Optional[str] = None
    usage: Any = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class BatchStatus:
    state: str  # "running" | "completed" | "failed"
    detail: str = ""
    responses: Dict[str, BatchItemResponse] = field(default_factory=dict)


def custom_id_for(index: int) -> str:
    return "req_%d" % index


def index_to_sample(batch_info: Dict[str, Any]) -> Dict[str, str]:
    """custom_id -> sample_id via the ordered list persisted at submit."""
    return {
        custom_id_for(index): sample_id
        for index, sample_id in enumerate(batch_info.get("sample_ids", []))
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def submit_batch(
    provider: str,
    model_config: Dict[str, Any],
    generation_defaults: Dict[str, Any],
    system_prompt: str,
    requests: List[Tuple[str, str]],
) -> Dict[str, Any]:
    """Submit one batch job; returns provider info incl. batch_id.
    `requests` is an ordered [(sample_id, request_text), ...]."""
    if provider == "anthropic":
        return _anthropic_submit(model_config, generation_defaults, system_prompt, requests)
    if provider == "openai":
        return _openai_submit(model_config, generation_defaults, system_prompt, requests)
    if provider == "gemini":
        return _gemini_submit(model_config, generation_defaults, system_prompt, requests)
    if provider == "openai_compatible":
        # only reached via an explicit api_mode_overrides force (the
        # orchestrator falls back to direct otherwise): OpenAI-style batch
        # against the configured base_url (e.g. DashScope compatible mode)
        return _openai_submit(
            model_config, generation_defaults, system_prompt, requests,
            chat_completions=True,
        )

    raise KeyError("No batch implementation for provider '%s'" % provider)


def poll_batch(
    provider: str,
    model_config: Dict[str, Any],
    batch_info: Dict[str, Any],
) -> BatchStatus:
    if provider == "anthropic":
        return _anthropic_poll(model_config, batch_info)
    if provider in ("openai", "openai_compatible"):
        return _openai_poll(model_config, batch_info)
    if provider == "gemini":
        return _gemini_poll(model_config, batch_info)

    raise KeyError("No batch implementation for provider '%s'" % provider)


# ---------------------------------------------------------------------------
# Anthropic (Message Batches API)
# ---------------------------------------------------------------------------


def _anthropic_client(model_config: Dict[str, Any]):
    from anthropic import Anthropic

    api_key = common.get_api_key(model_config, "ANTHROPIC_API_KEY")
    return Anthropic(api_key=api_key)


def _anthropic_thinking_payload(model_config: Dict[str, Any]) -> Dict[str, Any]:
    """thinking/effort request fields — imported from the direct-mode
    adapter (generate-anthropic.py) so batch requests are configured
    IDENTICALLY to direct requests (single mapping, no drift)."""
    import importlib.util

    path = REPO_ROOT / "thesis" / "generation" / "generate-anthropic.py"
    spec = importlib.util.spec_from_file_location("thesis_gen_anthropic", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    return module.thinking_payload(model_config)


def _anthropic_submit(model_config, generation_defaults, system_prompt, requests):
    client = _anthropic_client(model_config)
    max_tokens = int(
        common.get_param(model_config, generation_defaults, "max_output_tokens", 4096)
    )
    extra = _anthropic_thinking_payload(model_config)

    batch = client.messages.batches.create(
        requests=[
            {
                "custom_id": custom_id_for(index),
                "params": {
                    "model": model_config["model_name"],
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": text}],
                    **extra,
                },
            }
            for index, (_sample_id, text) in enumerate(requests)
        ]
    )

    return {"batch_id": batch.id}


def _anthropic_extract_text(message: Any) -> str:
    texts = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                texts.append(text)

    if not texts:
        raise RuntimeError("Could not extract text from Anthropic batch message.")

    return "\n".join(texts)


def _anthropic_poll(model_config, batch_info) -> BatchStatus:
    client = _anthropic_client(model_config)
    batch = client.messages.batches.retrieve(batch_info["batch_id"])
    processing = getattr(batch, "processing_status", None)

    if processing != "ended":
        return BatchStatus(state="running", detail=str(processing))

    mapping = index_to_sample(batch_info)
    responses: Dict[str, BatchItemResponse] = {}

    for entry in client.messages.batches.results(batch_info["batch_id"]):
        sample_id = mapping.get(entry.custom_id)
        if sample_id is None:
            continue

        result = entry.result
        result_type = getattr(result, "type", None)

        if result_type == "succeeded":
            message = result.message
            stop_reason = getattr(message, "stop_reason", None)

            if stop_reason == "refusal":
                responses[sample_id] = BatchItemResponse(
                    error_type="ModelRefusal",
                    error_message="stop_reason refusal",
                )
                continue

            try:
                raw_text = _anthropic_extract_text(message)
            except RuntimeError as error:
                responses[sample_id] = BatchItemResponse(
                    error_type="EmptyResponse", error_message=str(error)
                )
                continue

            responses[sample_id] = BatchItemResponse(
                raw_text=raw_text,
                finish_reason=stop_reason,
                truncated=stop_reason == "max_tokens",
                response_id=getattr(message, "id", None),
                usage=common.safe_model_dump(getattr(message, "usage", None)),
            )
        else:
            responses[sample_id] = BatchItemResponse(
                error_type="BatchItem%s" % str(result_type).capitalize(),
                error_message=str(common.safe_model_dump(getattr(result, "error", None))),
            )

    return BatchStatus(state="completed", detail="ended", responses=responses)


# ---------------------------------------------------------------------------
# OpenAI (file-based Batch API; also the forced openai_compatible path)
# ---------------------------------------------------------------------------


def _openai_client(model_config: Dict[str, Any], compatible: bool):
    from openai import OpenAI

    if compatible:
        # mirror generate-openai-compatible.py's client construction
        import importlib.util

        path = REPO_ROOT / "thesis" / "generation" / "generate-openai-compatible.py"
        spec = importlib.util.spec_from_file_location("thesis_gen_oai_compat", str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        api_key = common.get_api_key(model_config, "OPENAI_COMPATIBLE_API_KEY")
        return OpenAI(api_key=api_key, base_url=module.resolve_base_url(model_config))

    api_key = common.get_api_key(model_config, "OPENAI_API_KEY")
    return OpenAI(api_key=api_key)


def _openai_submit(model_config, generation_defaults, system_prompt, requests,
                   chat_completions=False):
    client = _openai_client(model_config, compatible=chat_completions)
    max_tokens = int(
        common.get_param(model_config, generation_defaults, "max_output_tokens", 4096)
    )

    lines = []
    for index, (_sample_id, text) in enumerate(requests):
        if chat_completions:
            # mirror generate-openai-compatible.py's payload
            body: Dict[str, Any] = {
                "model": model_config["model_name"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "max_tokens": max_tokens,
            }
            temperature = common.get_param(model_config, generation_defaults, "temperature")
            if temperature is not None:
                body["temperature"] = float(temperature)
            if model_config.get("extra_body"):
                body.update(model_config["extra_body"])
            url = "/v1/chat/completions"
        else:
            # mirror generate-openai.py's Responses-API payload
            body = {
                "model": model_config["model_name"],
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "max_output_tokens": max_tokens,
            }
            if model_config.get("reasoning_effort"):
                body["reasoning"] = {"effort": model_config["reasoning_effort"]}
            url = "/v1/responses"

        lines.append(json.dumps({
            "custom_id": custom_id_for(index),
            "method": "POST",
            "url": url,
            "body": body,
        }))

    data = ("\n".join(lines) + "\n").encode("utf-8")
    input_file = client.files.create(
        file=("repair_batch.jsonl", data), purpose="batch"
    )
    batch = client.batches.create(
        input_file_id=input_file.id,
        endpoint=url,
        completion_window="24h",
    )

    return {"batch_id": batch.id, "input_file_id": input_file.id,
            "endpoint": url}


def _openai_body_response(body: Dict[str, Any], chat: bool) -> BatchItemResponse:
    if chat:
        choices = body.get("choices") or []
        if not choices:
            return BatchItemResponse(error_type="EmptyResponse",
                                     error_message="no choices in batch body")
        message = choices[0].get("message") or {}
        finish_reason = choices[0].get("finish_reason")
        raw_text = message.get("content")
        if not raw_text:
            return BatchItemResponse(error_type="EmptyResponse",
                                     error_message="empty message content")
        return BatchItemResponse(
            raw_text=raw_text,
            finish_reason=finish_reason,
            truncated=finish_reason == "length",
            response_id=body.get("id"),
            usage=body.get("usage"),
        )

    # Responses API body (dict form of generate-openai.py's extraction)
    status = body.get("status")
    if status == "incomplete":
        reason = (body.get("incomplete_details") or {}).get("reason")
        finish_reason = "incomplete:%s" % reason if reason else "incomplete"
        truncated = reason == "max_output_tokens"
    else:
        finish_reason = status
        truncated = False

    texts = []
    output_text = body.get("output_text")
    if output_text:
        texts.append(output_text)
    else:
        for item in body.get("output") or []:
            for part in item.get("content") or []:
                text = part.get("text")
                if text:
                    texts.append(text)

    if not texts:
        return BatchItemResponse(error_type="EmptyResponse",
                                 error_message="no output text in batch body")

    return BatchItemResponse(
        raw_text="\n".join(texts),
        finish_reason=finish_reason,
        truncated=truncated,
        response_id=body.get("id"),
        usage=body.get("usage"),
    )


def _openai_poll(model_config, batch_info) -> BatchStatus:
    chat = batch_info.get("endpoint") == "/v1/chat/completions"
    client = _openai_client(model_config, compatible=chat)
    batch = client.batches.retrieve(batch_info["batch_id"])
    status = getattr(batch, "status", None)

    if status in ("validating", "in_progress", "finalizing"):
        return BatchStatus(state="running", detail=str(status))

    if status != "completed":
        return BatchStatus(state="failed", detail=str(status))

    mapping = index_to_sample(batch_info)
    responses: Dict[str, BatchItemResponse] = {}

    output_file_id = getattr(batch, "output_file_id", None)
    content = client.files.content(output_file_id).text if output_file_id else ""

    for line in content.splitlines():
        if not line.strip():
            continue

        entry = json.loads(line)
        sample_id = mapping.get(entry.get("custom_id"))
        if sample_id is None:
            continue

        if entry.get("error"):
            responses[sample_id] = BatchItemResponse(
                error_type="BatchItemError",
                error_message=json.dumps(entry["error"]),
            )
            continue

        response = entry.get("response") or {}
        if response.get("status_code") != 200:
            responses[sample_id] = BatchItemResponse(
                error_type="BatchItemHTTP%s" % response.get("status_code"),
                error_message=json.dumps(response.get("body"))[:500],
            )
            continue

        responses[sample_id] = _openai_body_response(response.get("body") or {}, chat)

    # requests missing from the output file surface via the error file /
    # remain unanswered; the orchestrator treats them as retryable
    return BatchStatus(state="completed", detail="completed", responses=responses)


# ---------------------------------------------------------------------------
# Gemini (google-genai inline batch; responses map by request order)
# ---------------------------------------------------------------------------


def _gemini_client(model_config: Dict[str, Any]):
    from google import genai

    api_key = common.get_api_key(model_config, "GEMINI_API_KEY")
    return genai.Client(api_key=api_key)


def _gemini_submit(model_config, generation_defaults, system_prompt, requests):
    from google.genai import types

    client = _gemini_client(model_config)
    max_tokens = int(
        common.get_param(model_config, generation_defaults, "max_output_tokens", 4096)
    )

    config_payload: Dict[str, Any] = {
        "system_instruction": system_prompt,
        "max_output_tokens": max_tokens,
    }

    temperature = common.get_param(model_config, generation_defaults, "temperature")
    if temperature is not None:
        config_payload["temperature"] = float(temperature)

    if model_config.get("thinking_level") is not None:
        config_payload["thinking_config"] = types.ThinkingConfig(
            thinking_level=model_config["thinking_level"]
        )

    inlined = [
        {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "config": dict(config_payload),
        }
        for _sample_id, text in requests
    ]

    job = client.batches.create(model=model_config["model_name"], src=inlined)

    return {"batch_id": job.name}


def _gemini_poll(model_config, batch_info) -> BatchStatus:
    client = _gemini_client(model_config)
    job = client.batches.get(name=batch_info["batch_id"])

    state = getattr(getattr(job, "state", None), "name", None) or str(
        getattr(job, "state", None)
    )

    if state in ("JOB_STATE_PENDING", "JOB_STATE_RUNNING", "JOB_STATE_QUEUED"):
        return BatchStatus(state="running", detail=state)

    if state != "JOB_STATE_SUCCEEDED":
        return BatchStatus(state="failed", detail=state)

    sample_ids = batch_info.get("sample_ids", [])
    inlined = getattr(getattr(job, "dest", None), "inlined_responses", None) or []
    responses: Dict[str, BatchItemResponse] = {}

    for index, item in enumerate(inlined):
        if index >= len(sample_ids):
            break
        sample_id = sample_ids[index]

        error = getattr(item, "error", None)
        if error:
            responses[sample_id] = BatchItemResponse(
                error_type="BatchItemError",
                error_message=str(common.safe_model_dump(error)),
            )
            continue

        response = getattr(item, "response", None)
        finish_reason = _gemini_finish_reason(response)

        try:
            raw_text = _gemini_extract_text(response)
        except RuntimeError as extract_error:
            responses[sample_id] = BatchItemResponse(
                error_type="EmptyResponse", error_message=str(extract_error)
            )
            continue

        responses[sample_id] = BatchItemResponse(
            raw_text=raw_text,
            finish_reason=finish_reason,
            truncated=finish_reason is not None and "MAX_TOKENS" in finish_reason,
            response_id=getattr(response, "response_id", None),
            usage=common.safe_model_dump(getattr(response, "usage_metadata", None)),
        )

    return BatchStatus(state="completed", detail=state, responses=responses)


def _gemini_finish_reason(response: Any) -> Optional[str]:
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return None
    finish_reason = getattr(candidates[0], "finish_reason", None)
    if finish_reason is None:
        return None
    return getattr(finish_reason, "name", None) or str(finish_reason)


def _gemini_extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    candidates = getattr(response, "candidates", None) or []
    texts = []

    for candidate in candidates:
        content = getattr(candidate, "content", None)
        for part in (getattr(content, "parts", None) or []):
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                texts.append(part_text)

    if not texts:
        raise RuntimeError("Could not extract text from Gemini batch response.")

    return "\n".join(texts)
