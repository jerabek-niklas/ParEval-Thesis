"""Tests for the generation runner (pattern: test_orchestrator.py).

Covers the parts that are easy to get subtly wrong:
  - timeout resolution (model override > generation_defaults > fallback)
  - api_mode resolution incl. the provider fallback to direct
  - the BATCH path: submit -> exit, --poll -> records, resume
  - the invariant that batch and direct produce the SAME record shape,
    because both go through apply_success/apply_failure

The batch provider is faked (no SDKs, no network); everything else runs
the real code in common.run_generation.

Run:  python thesis/generation/test_generation.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import batch_api, common  # noqa: E402

FAILURES = []


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


PROMPT_TEXT = (
    "/* Return the sum of x. */\ndouble sumArray(std::vector<double> const& x) {"
)

ANSWER = "    double s = 0;\n    for (auto v : x) s += v;\n    return s;\n}"


def write_world(tmp, api_mode="direct"):
    """Config + prompts file in a temp dir; returns (config_path, raw_dir)."""
    import yaml

    raw = Path(tmp) / "raw"
    prompts_path = Path(tmp) / "prompts.json"

    prompts_path.write_text(
        json.dumps([
            {"name": "27_reduce_average", "problem_type": "reduce",
             "language": "cpp", "parallelism_model": "serial",
             "prompt": PROMPT_TEXT},
            {"name": "28_reduce_sum", "problem_type": "reduce",
             "language": "cpp", "parallelism_model": "serial",
             "prompt": PROMPT_TEXT},
        ]),
        encoding="utf-8",
    )

    config = {
        "profiles": {"unit": {"run_id": "unit_run", "prompt_limit": None,
                              "num_samples_per_prompt": 1}},
        "prompts": {"path": prompts_path.as_posix(), "prompt_field": "prompt",
                    "execution_models": ["serial"], "problem_types": None},
        "generation_defaults": {
            "system_prompt": "You are a C++ assistant.",
            "max_output_tokens": 512,
            "timeout_seconds": 30,
            "retry_attempts": 0,
            "sleep_seconds_between_requests": 0.0,
            "api_mode": api_mode,
        },
        "outputs": {"raw_dir": raw.as_posix(),
                    "intermediate_dir": (Path(tmp) / "intermediate").as_posix()},
        "models": [{"id": "fake_model", "provider": "openai",
                    "model_name": "fake-1", "api_key_env": "FAKE_GEN_KEY",
                    "enabled": True}],
        "stages": {},
    }

    config_path = Path(tmp) / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    return config_path, raw / "unit_run" / "fake_model"


class FakeAdapter:
    provider = "openai"
    default_api_key_env = "FAKE_GEN_KEY"

    def __init__(self, behaviors=None):
        self.behaviors = list(behaviors or [])
        self.timeouts = []
        self.calls = 0

    def create_client(self, model_config, api_key, timeout_seconds=None):
        self.timeouts.append(timeout_seconds)
        return object()

    def generation_parameters(self, model_config, generation_defaults):
        return {"max_output_tokens": 512}

    def generate(self, client, model_config, generation_defaults, system_prompt,
                 messages, retry_attempts, sleep_seconds):
        self.calls += 1
        behavior = self.behaviors.pop(0) if self.behaviors else "ok"

        if behavior == "refuse":
            raise common.ModelRefusal("declined")
        if behavior == "error":
            raise RuntimeError("boom")

        return common.GenerationResult(
            raw_text=ANSWER, finish_reason="completed", truncated=False,
            response_id="resp-1", usage={"input_tokens": 10, "output_tokens": 20},
        )


def run_with(config_path, adapter, argv_extra=()):
    import os

    os.environ["FAKE_GEN_KEY"] = "x"
    old = sys.argv
    sys.argv = ["gen", "--config", str(config_path), "--profile", "unit",
                "--model-id", "fake_model"] + list(argv_extra)
    try:
        common.run_generation(adapter)
    finally:
        sys.argv = old


def read_records(out_dir):
    path = out_dir / "generations.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def test_timeout_resolution():
    print("timeout: model override > defaults > fallback")
    defaults = {"timeout_seconds": 120}
    check("defaults used", common.get_timeout_seconds({}, defaults) == 120.0)
    check("model overrides", common.get_timeout_seconds({"timeout_seconds": 5}, defaults) == 5.0)
    check("fallback when unset",
          common.get_timeout_seconds({}, {}) == common.DEFAULT_TIMEOUT_SECONDS)

    for bad in (0, -1):
        try:
            common.get_timeout_seconds({}, {"timeout_seconds": bad})
            check("non-positive %r rejected" % bad, False)
        except ValueError:
            check("non-positive %r rejected" % bad, True)


def test_api_mode_resolution():
    print("api_mode: default, override, provider fallback")
    check("default direct", common.resolve_api_mode({}, "openai")[0] == "direct")
    check("batch honored",
          common.resolve_api_mode({"api_mode": "batch"}, "openai")[0] == "batch")

    mode, note = common.resolve_api_mode({"api_mode": "batch"}, "openai_compatible")
    check("no batch API -> direct", mode == "direct")
    check("fallback is explained", note and "no verified batch API" in note)

    mode, _ = common.resolve_api_mode(
        {"api_mode": "batch", "api_mode_overrides": {"openai": "direct"}}, "openai"
    )
    check("per-provider override wins", mode == "direct")

    try:
        common.resolve_api_mode({"api_mode": "sometimes"}, "openai")
        check("unknown mode rejected", False)
    except ValueError:
        check("unknown mode rejected", True)


def test_direct_run():
    print("direct mode: records, resume, timeout reaches the client")

    with tempfile.TemporaryDirectory() as tmp:
        config_path, out_dir = write_world(tmp)
        adapter = FakeAdapter(["ok", "refuse"])

        run_with(config_path, adapter)

        records = read_records(out_dir)
        check("two records written", len(records) == 2)
        check("timeout handed to the client", adapter.timeouts == [30.0])
        check("success record cleaned",
              records[0]["output"]["cleaned_code"].startswith("double s = 0;"))
        check("refusal is not a success", records[1]["status"]["success"] is False)
        check("refusal typed", records[1]["status"]["error_type"] == "ModelRefusal")

        check("schema v3", records[0]["schema_version"] == "generation.v3")
        check("direct timing_mode on success",
              records[0]["status"]["timing_mode"] == "direct")
        check("direct timing_mode on refusal",
              records[1]["status"]["timing_mode"] == "direct")
        check("direct latency numeric",
              isinstance(records[0]["status"]["duration_seconds"], (int, float)))
        check("usage_normalized derived",
              records[0]["api_response"]["usage_normalized"]
              == {"input_tokens": 10, "output_tokens": 20, "reasoning_tokens": None})

        summary = json.loads((out_dir / "generation_summary.json").read_text(encoding="utf-8"))
        check("summary counts success", summary["counts"]["success"] == 1)
        check("summary counts refusal", summary["counts"]["refused"] == 1)
        check("summary records api_mode", summary["api_mode"] == "direct")

        # resume: the failed record is dropped and retried, the good one kept
        adapter2 = FakeAdapter(["ok"])
        run_with(config_path, adapter2)
        check("resume retries only the failed sample", adapter2.calls == 1)
        check("no duplicate sample_ids",
              len({r["sample_id"] for r in read_records(out_dir)}) == 2)


def test_batch_run():
    print("batch mode: submit -> poll -> same record path as direct")

    with tempfile.TemporaryDirectory() as tmp:
        config_path, out_dir = write_world(tmp, api_mode="batch")
        adapter = FakeAdapter()

        submitted = {}

        def fake_submit(provider, model_config, generation_defaults,
                        system_prompt, requests):
            submitted["requests"] = list(requests)
            submitted["system_prompt"] = system_prompt
            return {"batch_id": "batch-1"}

        state = {"polls": 0}

        def fake_poll(provider, model_config, batch_info):
            state["polls"] += 1
            if state["polls"] == 1:
                return batch_api.BatchStatus(state="running", detail="in_progress")

            responses = {
                batch_info["sample_ids"][0]: batch_api.BatchItemResponse(
                    raw_text=ANSWER, finish_reason="completed", truncated=False,
                    response_id="b-1", usage={"input_tokens": 10, "output_tokens": 20},
                ),
                batch_info["sample_ids"][1]: batch_api.BatchItemResponse(
                    error_type="ModelRefusal", error_message="declined",
                ),
            }
            return batch_api.BatchStatus(state="completed", detail="completed",
                                         responses=responses)

        original = (batch_api.submit_batch, batch_api.poll_batch)
        batch_api.submit_batch, batch_api.poll_batch = fake_submit, fake_poll

        try:
            # 1) submit and exit — nothing written yet
            run_with(config_path, adapter)
            check("submitted both samples", len(submitted["requests"]) == 2)
            check("prompt text submitted verbatim",
                  submitted["requests"][0][1] == PROMPT_TEXT)
            check("system prompt from config",
                  submitted["system_prompt"].startswith("You are a C++"))
            check("no records before the poll", read_records(out_dir) == [])
            check("no model call in batch mode", adapter.calls == 0)

            info = json.loads((out_dir / "generation_batch.json").read_text(encoding="utf-8"))
            check("batch id persisted", info["batch_id"] == "batch-1")
            check("ordered sample_ids persisted", len(info["sample_ids"]) == 2)

            # 2) poll while still running — still nothing written
            run_with(config_path, adapter, ["--poll"])
            check("still nothing written while running", read_records(out_dir) == [])

            # 3) poll after completion — records through the shared path
            run_with(config_path, adapter, ["--poll"])
            records = read_records(out_dir)
            check("two records after completion", len(records) == 2)

            by_id = {r["sample_id"]: r for r in records}
            good = by_id[info["sample_ids"][0]]
            bad = by_id[info["sample_ids"][1]]

            check("batch success record cleaned like direct",
                  good["output"]["cleaned_code"].startswith("double s = 0;"))
            check("batch success flagged", good["status"]["success"] is True)
            check("batch usage kept", good["api_response"]["usage"]["output_tokens"] == 20)
            check("batch refusal typed", bad["status"]["error_type"] == "ModelRefusal")
            check("batch refusal finish_reason", bad["output"]["finish_reason"] == "refusal")

            # batch timing semantics: NO latency, timestamps instead
            for label, record in (("success", good), ("refusal", bad)):
                check("batch %s timing_mode" % label,
                      record["status"]["timing_mode"] == "batch")
                check("batch %s has NO duration (queue time is not latency)" % label,
                      record["status"]["duration_seconds"] is None)
                check("batch %s carries both timestamps" % label,
                      isinstance(record["status"].get("batch_submitted_at_utc"), str)
                      and isinstance(record["status"].get("batch_completed_at_utc"), str))
            check("batch usage_normalized derived like direct",
                  good["api_response"]["usage_normalized"]["output_tokens"] == 20)

            summary = json.loads(
                (out_dir / "generation_summary.json").read_text(encoding="utf-8")
            )
            check("summary api_mode batch", summary["api_mode"] == "batch")
            check("summary counted the refusal", summary["counts"]["refused"] == 1)

            check("job file archived, not left pending",
                  not (out_dir / "generation_batch.json").exists()
                  and (out_dir / "generation_batch.done.json").exists())

            # 4) record shape is identical to direct mode
            direct_keys = None
            with tempfile.TemporaryDirectory() as tmp2:
                config2, out2 = write_world(tmp2)
                run_with(config2, FakeAdapter())
                direct_keys = sorted(read_records(out2)[0].keys())

            check("record schema identical to direct mode",
                  sorted(good.keys()) == direct_keys)
        finally:
            batch_api.submit_batch, batch_api.poll_batch = original


def test_reasoning_budget_exhausted():
    print("reasoning-budget exhaustion: specific error, terminal, no retry")
    import importlib.util
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location(
        "gen_oc_test", str(REPO_ROOT / "thesis" / "generation"
                           / "generate-openai-compatible.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # mocked DashScope response: finish_reason length, EMPTY content, all
    # completion tokens spent on reasoning (the measured smoke_002 shape)
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=""), finish_reason="length")],
        usage=SimpleNamespace(
            completion_tokens=16384,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=16384)),
    )

    try:
        mod.OpenAICompatibleAdapter._extract_text(response, "length")
        check("specific exception raised", False)
    except common.ReasoningBudgetExhausted as error:
        message = str(error)
        check("specific exception raised", True)
        check("usage numbers in the message",
              "reasoning_tokens=16384" in message
              and "16384 completion_tokens" in message)
    except Exception:
        check("specific exception raised", False)

    # empty content WITHOUT length keeps the generic error (extraction bug,
    # not a budget problem — must stay retryable)
    try:
        mod.OpenAICompatibleAdapter._extract_text(
            SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=""), finish_reason="stop")]),
            "stop")
        check("generic error for non-length empty content", False)
    except common.ReasoningBudgetExhausted:
        check("generic error for non-length empty content", False)
    except RuntimeError:
        check("generic error for non-length empty content", True)

    # end to end: the record is persisted with the diagnosis and NOT retried
    class BudgetFakeAdapter(FakeAdapter):
        def generate(self, *args, **kwargs):
            self.calls += 1
            raise common.ReasoningBudgetExhausted(
                "reasoning consumed the output budget (reasoning_tokens=16384 "
                "of 16384 completion_tokens)")

    with tempfile.TemporaryDirectory() as tmp:
        config_path, out_dir = write_world(tmp)
        adapter = BudgetFakeAdapter()
        run_with(config_path, adapter)

        records = read_records(out_dir)
        check("failed records persisted", len(records) == 2)
        check("error type recorded",
              records[0]["status"]["error_type"] == "ReasoningBudgetExhausted")
        check("diagnosis in the record",
              "reasoning consumed the output budget"
              in records[0]["status"]["error_message"])

        # resume: terminal — must NOT be dropped for retry
        adapter2 = BudgetFakeAdapter()
        run_with(config_path, adapter2)
        check("no retry on resume (terminal like ModelRefusal)",
              adapter2.calls == 0)
        check("records kept through resume", len(read_records(out_dir)) == 2)

        summary = json.loads(
            (out_dir / "generation_summary.json").read_text(encoding="utf-8"))
        check("resume counts them as existing",
              summary["counts"]["skipped_existing"] == 2)


def test_normalize_usage():
    print("usage normalization: five provider shapes -> one view")

    # OpenAI Responses API
    check("openai shape", common.normalize_usage(
        {"input_tokens": 100, "output_tokens": 50,
         "output_tokens_details": {"reasoning_tokens": 30}})
        == {"input_tokens": 100, "output_tokens": 50, "reasoning_tokens": 30})

    # Anthropic (thinking_tokens; adaptive zero is preserved as 0, not None)
    check("anthropic shape, explicit zero kept", common.normalize_usage(
        {"input_tokens": 100, "output_tokens": 50,
         "output_tokens_details": {"thinking_tokens": 0}})
        == {"input_tokens": 100, "output_tokens": 50, "reasoning_tokens": 0})

    # Gemini (flat thoughts_token_count, no details object)
    check("gemini shape", common.normalize_usage(
        {"prompt_token_count": 100, "candidates_token_count": 50,
         "thoughts_token_count": 77})
        == {"input_tokens": 100, "output_tokens": 50, "reasoning_tokens": 77})

    # DashScope chat completions
    check("dashscope shape", common.normalize_usage(
        {"prompt_tokens": 100, "completion_tokens": 50,
         "completion_tokens_details": {"reasoning_tokens": 12}})
        == {"input_tokens": 100, "output_tokens": 50, "reasoning_tokens": 12})

    # DashScope non-thinking model: details is null -> reasoning None
    check("null details -> reasoning None", common.normalize_usage(
        {"prompt_tokens": 100, "completion_tokens": 50,
         "completion_tokens_details": None})["reasoning_tokens"] is None)

    check("non-dict usage -> None", common.normalize_usage("repr(...)") is None)
    check("None usage -> None", common.normalize_usage(None) is None)
    check("bool is not a count", common.normalize_usage(
        {"input_tokens": True, "output_tokens": 5})["input_tokens"] is None)


def test_reasoning_evidence():
    print("reasoning evidence: policy detection + warning cases")

    check("anthropic effort expects", common.reasoning_expected({"effort": "medium"}))
    check("anthropic thinking expects",
          common.reasoning_expected({"thinking": "adaptive"}))
    check("openai effort expects",
          common.reasoning_expected({"reasoning_effort": "medium"}))
    check("gemini level expects",
          common.reasoning_expected({"thinking_level": "medium"}))
    check("dashscope enable_thinking expects",
          common.reasoning_expected({"extra_body": {"enable_thinking": True}}))
    check("non-thinking model does not expect",
          not common.reasoning_expected({"extra_body": {"thinking_budget": 8192}}))
    check("empty config does not expect", not common.reasoning_expected({}))

    def record_with(reasoning):
        return {"sample_id": "s1", "api_response": {"usage_normalized": {
            "input_tokens": 1, "output_tokens": 1, "reasoning_tokens": reasoning}}}

    thinking_config = {"effort": "medium"}

    warning = common.reasoning_evidence_warning(record_with(None), thinking_config)
    check("missing field warns about ignored parameter",
          warning is not None and "may be ignored" in warning)

    warning = common.reasoning_evidence_warning(record_with(0), thinking_config)
    check("explicit zero warns softly (adaptive)",
          warning is not None and "adaptive" in warning)

    check("actual reasoning -> no warning",
          common.reasoning_evidence_warning(record_with(500), thinking_config) is None)
    check("non-thinking model -> no warning",
          common.reasoning_evidence_warning(record_with(None), {}) is None)


def test_validator_timing():
    print("validator: v3 timing rules, v2 back-compat")
    from thesis.generation import validate_generations as vg

    prompt = {"name": "27_reduce_average", "problem_type": "reduce",
              "language": "cpp", "parallelism_model": "serial",
              "prompt": PROMPT_TEXT}
    summary = {"counts": {"success": 0, "truncated": 0, "refused": 0, "error": 0}}

    def fresh_record():
        record = common.build_empty_record(
            run_id="unit", model_config={"id": "m", "provider": "openai",
                                         "model_name": "fake"},
            prompt=prompt, prompt_field="prompt", sample_index=0,
            generation_parameters={},
        )
        common.apply_success(record, summary, ANSWER, "completed", False,
                             "r-1", {"input_tokens": 1, "output_tokens": 2})
        return record

    direct = fresh_record()
    common.apply_direct_timing(direct, started_at=0.0)
    # apply_direct_timing measures against wall clock; rewrite for a stable test
    direct["status"]["duration_seconds"] = 1.5
    errors, _ = vg.validate_record(direct)
    check("valid direct v3 record passes", errors == [])

    batch = fresh_record()
    common.apply_batch_timing(batch, "2026-08-01T00:00:00Z", "2026-08-01T04:00:00Z")
    errors, _ = vg.validate_record(batch)
    check("valid batch v3 record passes", errors == [])

    bad_batch = fresh_record()
    common.apply_batch_timing(bad_batch, "2026-08-01T00:00:00Z", "2026-08-01T04:00:00Z")
    bad_batch["status"]["duration_seconds"] = 14400.0  # the queue-time mistake
    errors, _ = vg.validate_record(bad_batch)
    check("batch record with duration rejected",
          any("queue time" in e for e in errors))

    no_stamps = fresh_record()
    common.apply_batch_timing(no_stamps, None, None)
    errors, _ = vg.validate_record(no_stamps)
    check("batch record without timestamps rejected",
          sum("batch_" in e for e in errors) == 2)

    no_mode = fresh_record()
    no_mode["status"]["timing_mode"] = None
    errors, _ = vg.validate_record(no_mode)
    check("v3 without timing_mode rejected",
          any("timing_mode" in e for e in errors))

    legacy = fresh_record()
    legacy["schema_version"] = "generation.v2"
    del legacy["status"]["timing_mode"]
    legacy["status"]["duration_seconds"] = 1.5
    errors, _ = vg.validate_record(legacy)
    check("v2 legacy record still validates without timing fields",
          errors == [])


def main():
    tests = [
        test_timeout_resolution,
        test_api_mode_resolution,
        test_direct_run,
        test_batch_run,
        test_reasoning_budget_exhausted,
        test_normalize_usage,
        test_reasoning_evidence,
        test_validator_timing,
    ]

    for test in tests:
        test()
        print()

    if FAILURES:
        print("FAILED (%d):" % len(FAILURES))
        for label in FAILURES:
            print("  - %s" % label)
        sys.exit(1)

    print("All %d generation test groups passed." % len(tests))


if __name__ == "__main__":
    main()
