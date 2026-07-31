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


def main():
    tests = [
        test_timeout_resolution,
        test_api_mode_resolution,
        test_direct_run,
        test_batch_run,
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
