"""Tests for the repair-loop orchestrator (pattern: test_feedback.py).

Covers (task Teil 6):
  - stop logic per variant (static findings only / tests fail / all clean)
  - grace_once semantics (new vs. persisted vs. shifted line)
  - repair_unusable handling (refusal, unassemblable answer)
  - resume in the middle of every phase (fresh RepairLoop instance per
    step over persisted state — the orchestrator must continue correctly)
  - batch fallback for providers without a batch API
  - manual external-tools waiting (analyzed_waiting_external)

The full-loop scenarios build a fake world in a temp directory and stub
ONLY the analysis stages (they need the container toolchain); request
building, direct submission, response records, and assembly run the real
code paths (assemble_sources cleaning included).

Run:  python thesis/repair/test_orchestrator.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import common  # noqa: E402
from thesis.repair import feedback, orchestrator  # noqa: E402
from thesis.repair.orchestrator import (  # noqa: E402
    STATUS_ACTIVE,
    STATUS_BUDGET,
    STATUS_CLEAN,
    STATUS_TESTS_PASS,
    STATUS_UNUSABLE,
    RepairLoop,
    evaluate_stop,
)

FAILURES = []


def check(label, condition):
    status = "ok" if condition else "FAIL"
    print("  [%s] %s" % (status, label))
    if not condition:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Fixtures: records
# ---------------------------------------------------------------------------


def finding(tool, check_id, message, line=3, blocking=True, low_confidence=False):
    return {
        "tool": tool,
        "check_id": check_id,
        "severity": "error" if blocking else "info",
        "message": message,
        "file": "generated-code.hpp",
        "line": line,
        "column": 1,
        "blocking": blocking,
        "low_confidence": low_confidence,
    }


def static_record(findings_by_tool):
    return {
        "sample_id": "s",
        "tools": {
            tool: {"tool": tool, "ran": True, "findings": findings}
            for tool, findings in findings_by_tool.items()
        },
    }


def dynamic_record(findings_by_tool=None):
    return static_record(findings_by_tool or {"tsan": []})


def correctness_record(verdict):
    return {
        "sample_id": "s",
        "verdict": verdict,
        "execution_model": "omp",
        "runs": [
            {"params": {"num_threads": 4}, "verdict": verdict},
        ],
    }


def stop_config(**repair_overrides):
    repair = {
        "max_iterations": 3,
        "low_confidence_stop_mode": "grace_once",
    }
    repair.update(repair_overrides)

    return {
        "stages": {
            "static_analysis": {
                "tools": {
                    "compiler": {"enabled": True},
                    "clang_tidy": {"enabled": True},
                    # off here so the fixture's static records stay a minimal
                    # two-tool set; gcc_analyzer is enabled in the real config
                    "gcc_analyzer": {"enabled": False},
                    "cppcheck": {"enabled": False},
                    "infer": {"enabled": False},
                    "parcoach": {"enabled": True, "execution_models": ["mpi"],
                                 "low_precision_warning": True},
                    "llov": {"enabled": False},
                }
            },
            "dynamic_analysis": {
                "tools": {
                    "asan_ubsan": {"enabled": False},
                    "tsan": {"enabled": True},
                    "memcheck": {"enabled": False},
                    "must": {"enabled": False},
                }
            },
            "repair": repair,
        }
    }


CLEAN_STATIC = static_record({"compiler": [], "clang_tidy": []})


# ---------------------------------------------------------------------------
# Group 1: stop logic per variant
# ---------------------------------------------------------------------------


def test_stop_logic():
    print("stop logic per variant")
    config = stop_config()

    # static variant: blocking static finding -> active
    decision = evaluate_stop(
        config, "static_feedback", 1, 3,
        static_record({"compiler": [], "clang_tidy": [finding("clang_tidy", "bugprone-x", "bad")]}),
        None, None, None,
    )
    check("static blocking -> active", decision.status == STATUS_ACTIVE)
    check("reason names blocking", "blocking" in decision.stop_reason)

    # compile error blocks in EVERY variant (compiler rule)
    decision = evaluate_stop(
        config, "test_feedback", 1, 3,
        static_record({"compiler": [finding("compiler", "error", "no match")]}),
        dynamic_record(), correctness_record("pass"), None,
    )
    check("compile error blocks test_feedback", decision.status == STATUS_ACTIVE)
    check("compile error counted", decision.counts["compile_errors"] == 1)

    # static clean -> stopped_clean (even if tests would fail: not a source)
    decision = evaluate_stop(
        config, "static_feedback", 1, 3, CLEAN_STATIC, None, None, None
    )
    check("static clean -> stopped_clean", decision.status == STATUS_CLEAN)

    # test variant: tests fail -> active
    decision = evaluate_stop(
        config, "test_feedback", 1, 3,
        CLEAN_STATIC, dynamic_record(), correctness_record("validation_failed"), None,
    )
    check("tests fail -> active", decision.status == STATUS_ACTIVE)
    check("verdict recorded", decision.test_verdict == "validation_failed")

    # test variant: tests pass + dynamic blocking -> active
    decision = evaluate_stop(
        config, "test_feedback", 1, 3,
        CLEAN_STATIC,
        dynamic_record({"tsan": [finding("tsan", "data-race", "race")]}),
        correctness_record("pass"), None,
    )
    check("dynamic blocking -> active", decision.status == STATUS_ACTIVE)

    # test variant: all clean -> stopped_tests_pass
    decision = evaluate_stop(
        config, "test_feedback", 1, 3,
        CLEAN_STATIC, dynamic_record(), correctness_record("pass"), None,
    )
    check("tests pass + dynamic clean -> stopped_tests_pass",
          decision.status == STATUS_TESTS_PASS)

    # combined: static clean but tests fail -> active
    decision = evaluate_stop(
        config, "combined_feedback", 1, 3,
        CLEAN_STATIC, dynamic_record(), correctness_record("validation_failed"), None,
    )
    check("combined: tests fail -> active", decision.status == STATUS_ACTIVE)

    # combined all clean -> stopped_clean
    decision = evaluate_stop(
        config, "combined_feedback", 1, 3,
        CLEAN_STATIC, dynamic_record(), correctness_record("pass"), None,
    )
    check("combined clean -> stopped_clean", decision.status == STATUS_CLEAN)

    # budget: unresolved at max_iterations -> stopped_budget
    decision = evaluate_stop(
        config, "static_feedback", 3, 3,
        static_record({"compiler": [finding("compiler", "error", "boom")]}),
        None, None, None,
    )
    check("budget exhausted -> stopped_budget", decision.status == STATUS_BUDGET)
    check("budget reason keeps issues", "compile error" in decision.stop_reason)

    # disabled tool findings are invisible (tool_config single source)
    decision = evaluate_stop(
        config, "static_feedback", 1, 3,
        static_record({"compiler": [], "clang_tidy": [],
                       "cppcheck": [finding("cppcheck", "x", "disabled tool")]}),
        None, None, None,
    )
    check("disabled tool invisible -> stopped_clean", decision.status == STATUS_CLEAN)

    # non-blocking findings never stop the loop
    decision = evaluate_stop(
        config, "static_feedback", 1, 3,
        static_record({"compiler": [],
                       "clang_tidy": [finding("clang_tidy", "style", "hint", blocking=False)]}),
        None, None, None,
    )
    check("non-blocking only -> stopped_clean", decision.status == STATUS_CLEAN)
    check("non-blocking counted", decision.counts["non_blocking"] == 1)

    # missing required record fails loudly
    try:
        evaluate_stop(config, "test_feedback", 1, 3, CLEAN_STATIC, dynamic_record(), None, None)
        check("missing correctness record raises", False)
    except ValueError:
        check("missing correctness record raises", True)


# ---------------------------------------------------------------------------
# Group 2: grace_once semantics
# ---------------------------------------------------------------------------


def lc_static(line):
    return static_record({
        "compiler": [],
        "clang_tidy": [],
        "parcoach": [finding("parcoach", "parcoach-collective", "mismatch",
                             line=line, low_confidence=True)],
    })


def test_grace_once():
    print("grace_once semantics")
    config = stop_config()

    # new low_confidence finding (no previous keys) -> blocks (grace round)
    decision = evaluate_stop(
        config, "static_feedback", 1, 3, lc_static(7), None, None, None
    )
    check("new lc finding blocks", decision.status == STATUS_ACTIVE)
    check("lc effective counted", decision.counts["low_confidence_effective"] == 1)
    check("keys persisted", decision.low_confidence_keys == [["parcoach-collective", 7]])

    # same key persisted from previous iteration -> stops counting
    decision = evaluate_stop(
        config, "static_feedback", 2, 3, lc_static(7), None, None,
        [["parcoach-collective", 7]],
    )
    check("persisted lc finding stops counting", decision.status == STATUS_CLEAN)
    check("lc still reported in counts", decision.counts["low_confidence"] == 1)
    check("lc effective zero", decision.counts["low_confidence_effective"] == 0)

    # shifted line -> changed code -> new grace
    decision = evaluate_stop(
        config, "static_feedback", 2, 3, lc_static(9), None, None,
        [["parcoach-collective", 7]],
    )
    check("shifted line re-grants grace", decision.status == STATUS_ACTIVE)

    # mode ignore: never counts
    decision = evaluate_stop(
        stop_config(low_confidence_stop_mode="ignore"),
        "static_feedback", 1, 3, lc_static(7), None, None, None,
    )
    check("ignore mode -> stopped_clean", decision.status == STATUS_CLEAN)

    # mode always_blocking: counts even when persisted
    decision = evaluate_stop(
        stop_config(low_confidence_stop_mode="always_blocking"),
        "static_feedback", 2, 3, lc_static(7), None, None,
        [["parcoach-collective", 7]],
    )
    check("always_blocking keeps blocking", decision.status == STATUS_ACTIVE)

    # non-blocking low_confidence never counts (any mode)
    record = static_record({
        "compiler": [], "clang_tidy": [],
        "parcoach": [finding("parcoach", "hint", "weak", blocking=False,
                             low_confidence=True)],
    })
    decision = evaluate_stop(
        stop_config(low_confidence_stop_mode="always_blocking"),
        "static_feedback", 1, 3, record, None, None, None,
    )
    check("non-blocking lc never counts", decision.status == STATUS_CLEAN)


# ---------------------------------------------------------------------------
# Fake world for the loop scenarios
# ---------------------------------------------------------------------------

PROMPT_TEXT = (
    "/* Return the sum of the vector x.\n"
    "   Example: sumArray({1.0, 2.0}) == 3.0\n"
    "*/\n"
    "double sumArray(std::vector<double> const& x) {"
)

FIXED_ANSWER = (
    "double sumArray(std::vector<double> const& x) {\n"
    "    double sum = 0.0;\n"
    "    for (size_t i = 0; i < x.size(); ++i) {\n"
    "        sum += x[i];\n"
    "    }\n"
    "    return sum;\n"
    "}\n"
)


def make_world(tmp, execution_model="serial", enable_parcoach=False,
               repair_overrides=None):
    raw = Path(tmp) / "raw"
    intermediate = Path(tmp) / "intermediate"
    sample_id = "fake_model__reduce__27_reduce_average__%s__sample_0" % execution_model

    config = {
        "outputs": {
            "raw_dir": raw.as_posix(),
            "intermediate_dir": intermediate.as_posix(),
        },
        "generation_defaults": {
            "system_prompt": "You are a C++ assistant.",
            "retry_attempts": 0,
            "sleep_seconds_between_requests": 0.0,
            "max_output_tokens": 512,
        },
        "models": [
            {
                "id": "fake_model",
                "provider": "openai_compatible",
                "model_name": "fake-model",
                "api_key_env": "FAKE_REPAIR_KEY",
                "enabled": True,
            }
        ],
        "stages": {
            "assembly": {"auto_close_single_brace": True},
            "static_analysis": {
                "tools": {
                    "compiler": {"enabled": True},
                    "clang_tidy": {"enabled": True},
                    # off here so the fixture's static records stay a minimal
                    # two-tool set; gcc_analyzer is enabled in the real config
                    "gcc_analyzer": {"enabled": False},
                    "cppcheck": {"enabled": False},
                    "infer": {"enabled": False},
                    "parcoach": {
                        "enabled": enable_parcoach,
                        "execution_models": ["mpi"],
                        "low_precision_warning": True,
                    },
                    "llov": {"enabled": False},
                }
            },
            "dynamic_analysis": {
                "tools": {
                    "asan_ubsan": {"enabled": False},
                    "tsan": {"enabled": False},
                    "memcheck": {"enabled": False},
                    "must": {"enabled": False},
                }
            },
            "correctness_tests": {},
            "repair": {
                "max_iterations": 3,
                "variants": ["static_feedback"],
                "api_mode": "direct",
                "external_tools_mode": "manual",
            },
        },
    }

    config["stages"]["repair"].update(repair_overrides or {})

    profile = {"run_id": "base_run"}
    model_config = config["models"][0]

    # base generation record (iteration 0 comes from the shared run)
    base_record = {
        "schema_version": "generation.v2",
        "run_id": "base_run",
        "sample_id": sample_id,
        "model": {"id": "fake_model", "provider": "openai_compatible",
                  "model_name": "fake-model"},
        "prompt": {
            "problem_type": "reduce",
            "name": "27_reduce_average",
            "language": "cpp",
            "parallelism_model": execution_model,
            "prompt_field": "prompt",
            "prompt_text": PROMPT_TEXT,
        },
        "generation_parameters": {"sample_index": 0},
        "output": {"raw_text": "    return 0.0;\n}"},
        "status": {"success": True, "truncated": False},
    }
    common.append_jsonl(raw / "base_run" / "fake_model" / "generations.jsonl",
                        base_record)

    # base assembled artifact (broken on purpose: returns 0.0)
    source_path = (
        intermediate / "base_run" / "fake_model" / "sources" / sample_id
        / "generated-code.hpp"
    )
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(PROMPT_TEXT + "\n    return 0.0;\n}\n", encoding="utf-8")

    common.append_jsonl(
        intermediate / "base_run" / "fake_model" / "assembly.jsonl",
        {
            "sample_id": sample_id,
            "assembled": True,
            "source_path": source_path.as_posix(),
            "drivers": {
                "benchmark_dir": "drivers/cpp/benchmarks/reduce/27_reduce_average",
                "model_driver": "drivers/cpp/models/serial-driver.cc",
            },
        },
    )

    os.environ["FAKE_REPAIR_KEY"] = "fake-key"

    return config, profile, model_config, sample_id


class FakeAdapter:
    """Scriptable provider adapter: a list of behaviors, one per call.
    'ok' returns FIXED_ANSWER; 'refuse' raises ModelRefusal; 'error'
    raises a transport error; 'garbage' returns unparseable prose."""

    provider = "openai_compatible"
    default_api_key_env = "FAKE_REPAIR_KEY"

    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.calls = []

    def create_client(self, model_config, api_key, timeout_seconds=None):
        self.client_timeout = timeout_seconds
        return object()

    def generation_parameters(self, model_config, generation_defaults):
        return {"fake": True}

    def generate(self, client, model_config, generation_defaults, system_prompt,
                 messages, retry_attempts, sleep_seconds):
        self.calls.append(messages)
        behavior = self.behaviors.pop(0) if self.behaviors else "ok"

        if behavior == "refuse":
            raise common.ModelRefusal("declined")
        if behavior == "error":
            raise RuntimeError("simulated transport failure")

        return common.GenerationResult(
            raw_text=FIXED_ANSWER,
            finish_reason="stop",
            truncated=False,
            response_id="fake-response",
            usage={"prompt_tokens": 42, "completion_tokens": 17},
        )


class StubLoop(RepairLoop):
    """RepairLoop with the analysis stages stubbed (the only part that
    needs the container toolchain). Iteration 0 gets a blocking compiler
    finding; iterations >= 1 are clean — so one repair wave must end the
    loop in stopped_clean. `parcoach_missing` leaves the external tool's
    records out to exercise analyzed_waiting_external."""

    parcoach_missing = False
    clean_from_iteration = 1

    def _run_analysis_stages(self, iteration, stages):
        samples = self.iteration_samples(iteration)
        path = self.paths.stage_path(iteration, "static_analysis")
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as handle:
            for sample_id in samples:
                if iteration < self.clean_from_iteration:
                    compiler_findings = [
                        finding("compiler", "error",
                                "use of undeclared identifier 'summ'", line=6)
                    ]
                else:
                    compiler_findings = []

                tools = {
                    "compiler": {"tool": "compiler", "ran": True,
                                 "findings": compiler_findings},
                    "clang_tidy": {"tool": "clang_tidy", "ran": True,
                                   "findings": []},
                }
                handle.write(json.dumps({
                    "sample_id": sample_id,
                    "run_id": self.paths.iter_run_id(iteration),
                    "execution_model": execution_model_of_test(sample_id),
                    "tools": tools,
                }) + "\n")


def execution_model_of_test(sample_id):
    return sample_id.split("__")[-2]


def make_loop(config, profile, model_config, adapter, loop_cls=StubLoop,
              variant="static_feedback"):
    return loop_cls(
        config=config,
        config_path="thesis/config/config.yaml",
        profile_name="unit",
        profile=profile,
        model_config=model_config,
        variant=variant,
        adapter_factory=lambda provider: adapter,
    )


# ---------------------------------------------------------------------------
# Group 3: full wave with resume after every step
# ---------------------------------------------------------------------------


def test_full_wave_with_resume():
    print("full wave (direct) with restart after every step")

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp)
        adapter = FakeAdapter(["ok"])

        expected = [
            ("advanced", "analyzed", 0),
            ("decided", "decided", 0),
            ("advanced", "requests_built", 1),
            ("advanced", "responses_merged", 1),
            ("advanced", "assembled", 1),
            ("advanced", "analyzed", 1),
            ("decided", "decided", 1),
            ("done", "done", 1),
        ]

        for step_index, (want_outcome, want_phase, want_iter) in enumerate(expected):
            # fresh instance per step == process restart between steps
            loop = make_loop(config, profile, model_config, adapter)
            outcome = loop.step()
            wave = loop.load_wave_state()

            ok = (
                outcome == want_outcome
                and wave["phase"] == want_phase
                and int(wave["iteration"]) == want_iter
            )
            check(
                "step %d -> %s/%s(%d)" % (step_index, want_outcome, want_phase, want_iter),
                ok,
            )
            if not ok:
                print("       got %s/%s(%s)" % (outcome, wave["phase"], wave["iteration"]))

        loop = make_loop(config, profile, model_config, adapter)
        states = loop.sample_states()
        final = states[sample_id]
        check("final status stopped_clean", final["status"] == STATUS_CLEAN)
        check("final decision at iteration 1", final["iteration"] == 1)

        # request content: original prompt, current code, rendered finding
        requests = loop.load_requests(1)
        check("one request built", len(requests) == 1)
        request_text = requests[0]["request"] if requests else ""
        check("request contains task prompt", "Return the sum of the vector" in request_text)
        check("request contains compiler finding",
              "use of undeclared identifier" in request_text)
        check("request contains current code", "return 0.0;" in request_text)
        check("driver-error template NOT used for model-file finding",
              "test driver" not in request_text)

        # response record: usage logged, repair identity present
        with loop.paths.iter_generations_path(1).open("r", encoding="utf-8") as handle:
            response = json.loads(handle.readline())
        check("usage tokens logged",
              (response.get("api_response") or {}).get("usage", {}).get("prompt_tokens") == 42)
        check("repair identity on response",
              response.get("repair", {}).get("iteration") == 1)
        check("sample_id unchanged across iterations",
              response.get("sample_id") == sample_id)

        # iteration-1 artifact went through the real assembly cleaning
        source = loop.paths.source_path(1, sample_id).read_text(encoding="utf-8")
        check("iter1 source assembled with NO_INLINE",
              "NO_INLINE" in source and "sum += x[i];" in source)
        check("iter1 source keeps prompt head", "Example: sumArray" in source)

        # decide idempotency: re-deciding the same iteration adds nothing
        loop = make_loop(config, profile, model_config, adapter)
        before = loop.paths.state_path.read_text(encoding="utf-8").count("\n")
        loop._decide(1)
        after = loop.paths.state_path.read_text(encoding="utf-8").count("\n")
        check("decide is idempotent (no duplicate state records)", before == after)

        check("exactly one API call made", len(adapter.calls) == 1)


def test_dry_run_history_modes():
    print("dry-run renders the wave in both history modes")

    class NeverCleanLoop(StubLoop):
        # stays dirty so the loop keeps producing waves
        clean_from_iteration = 99

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(
            tmp, repair_overrides={"max_iterations": 5, "history_mode": "full"}
        )
        adapter = FakeAdapter(["ok"] * 10)

        def loop():
            return make_loop(config, profile, model_config, adapter,
                             loop_cls=NeverCleanLoop)

        # iteration 1 has no history yet -> both modes must be identical
        while loop().load_wave_state()["phase"] != "decided":
            loop().step()

        first = loop().dry_run()
        check("dry-run summary returned", first is not None)
        check("target iteration 1", first["iteration"] == 1)
        check("iteration 1: modes identical (no history yet)",
              first["chars"]["full"] == first["chars"]["compressed"])

        # advance one full wave, then compare again at iteration 2
        target = loop()
        while target.load_wave_state()["iteration"] < 1 or \
                target.load_wave_state()["phase"] != "decided":
            target.step()
            target = loop()

        second = loop().dry_run()
        check("target iteration 2", second["iteration"] == 2)
        check("iteration 2: full is larger than compressed",
              second["chars"]["full"] > second["chars"]["compressed"])
        check("nothing written by dry-run",
              loop().load_wave_state()["phase"] == "decided")

        # the override must not leak into the loop's own configuration
        check("configured mode untouched",
              feedback.history_mode(config) == "full")

        # both sides go through the SAME builder
        overlaid = orchestrator.config_with_history_mode(config, "compressed")
        check("overlay switches the mode",
              feedback.history_mode(overlaid) == "compressed")
        check("overlay does not mutate the original",
              feedback.history_mode(config) == "full")


# ---------------------------------------------------------------------------
# Group 4: transport failure -> blocked_api -> retry on rerun
# ---------------------------------------------------------------------------


def test_transport_retry():
    print("transport failure blocks, rerun retries")

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp)
        adapter = FakeAdapter(["error", "ok"])

        loop = make_loop(config, profile, model_config, adapter)
        outcome = loop.run()
        check("run blocks on transport failure", outcome == "blocked_api")
        wave = loop.load_wave_state()
        check("phase stays requests_built", wave["phase"] == "requests_built")

        # rerun: failed record is dropped and retried
        loop = make_loop(config, profile, model_config, adapter)
        outcome = loop.run()
        check("rerun finishes the loop", outcome == "done")
        final = loop.sample_states()[sample_id]
        check("final status stopped_clean after retry", final["status"] == STATUS_CLEAN)
        check("two API calls total", len(adapter.calls) == 2)


# ---------------------------------------------------------------------------
# Group 5: refusal -> repair_unusable (terminal, no endless retry)
# ---------------------------------------------------------------------------


def test_refusal_unusable():
    print("refusal ends the sample as repair_unusable")

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp)
        adapter = FakeAdapter(["refuse"])

        loop = make_loop(config, profile, model_config, adapter)
        outcome = loop.run()
        check("loop ends", outcome == "done")

        final = loop.sample_states()[sample_id]
        check("status repair_unusable", final["status"] == STATUS_UNUSABLE)
        check("reason mentions refusal", "refus" in final["stop_reason"])
        check("no second API call", len(adapter.calls) == 1)


# ---------------------------------------------------------------------------
# Group 6: manual external-tools waiting (parcoach)
# ---------------------------------------------------------------------------


def test_external_waiting():
    print("analyzed_waiting_external (manual mode)")

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(
            tmp, execution_model="mpi", enable_parcoach=True
        )
        adapter = FakeAdapter([])

        class ParcoachStubLoop(StubLoop):
            pass  # stub writes static records WITHOUT parcoach entries

        loop = make_loop(config, profile, model_config, adapter,
                         loop_cls=ParcoachStubLoop)
        outcome = loop.step()
        check("blocks waiting for external tool", outcome == "blocked_external")
        wave = loop.load_wave_state()
        check("phase analyzed_waiting_external",
              wave["phase"] == "analyzed_waiting_external")

        pending = loop.paths.pending_external_path.read_text(encoding="utf-8")
        check("pending file names parcoach", "--tools parcoach" in pending)
        check("pending file carries the iteration run id",
              "--run-id base_run" in pending)

        # restart without the external run: still blocked (no progress)
        loop = make_loop(config, profile, model_config, adapter,
                         loop_cls=ParcoachStubLoop)
        check("still blocked before external run", loop.step() == "blocked_external")

        # simulate the container run: merge parcoach entries into the file
        static_path = loop.paths.stage_path(0, "static_analysis")
        records = [json.loads(line) for line in
                   static_path.read_text(encoding="utf-8").splitlines() if line]
        for record in records:
            record["tools"]["parcoach"] = {"tool": "parcoach", "ran": True,
                                           "findings": []}
        static_path.write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
        )

        loop = make_loop(config, profile, model_config, adapter,
                         loop_cls=ParcoachStubLoop)
        outcome = loop.step()
        check("advances after external records exist", outcome == "advanced")
        check("pending file cleared",
              not loop.paths.pending_external_path.exists())
        check("phase analyzed", loop.load_wave_state()["phase"] == "analyzed")

        # test_feedback never waits for external static tools
        loop_tests = make_loop(config, profile, model_config, adapter,
                               loop_cls=ParcoachStubLoop, variant="test_feedback")
        check("test_feedback ignores external tools",
              loop_tests.pending_external(0) == [])


# ---------------------------------------------------------------------------
# Group 7: budget stop over multiple waves
# ---------------------------------------------------------------------------


def test_budget_stop():
    print("budget stop at max_iterations")

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp)
        config["stages"]["repair"]["max_iterations"] = 2
        adapter = FakeAdapter(["ok"] * 10)

        class NeverCleanLoop(StubLoop):
            clean_from_iteration = 99  # findings never go away

        loop = make_loop(config, profile, model_config, adapter,
                         loop_cls=NeverCleanLoop)
        outcome = loop.run()
        check("loop ends", outcome == "done")

        final = loop.sample_states()[sample_id]
        check("status stopped_budget", final["status"] == STATUS_BUDGET)
        check("stopped at iteration 2", final["iteration"] == 2)
        check("exactly max_iterations API calls", len(adapter.calls) == 2)

        # every iteration decided exactly once on the state trail
        states = [json.loads(line) for line in
                  loop.paths.state_path.read_text(encoding="utf-8").splitlines()
                  if line]
        iterations = [s["iteration"] for s in states]
        check("decisions at iterations 0,1,2", iterations == [0, 1, 2])


# ---------------------------------------------------------------------------
# Group 8: --max-wave bounds the run
# ---------------------------------------------------------------------------


def test_max_wave():
    print("--max-wave bounds the invocation")

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp)
        adapter = FakeAdapter(["ok"] * 10)

        class NeverCleanLoop(StubLoop):
            clean_from_iteration = 99

        loop = make_loop(config, profile, model_config, adapter,
                         loop_cls=NeverCleanLoop)
        loop.run(max_waves=1)
        wave = loop.load_wave_state()
        check("stopped after wave 1 (decided iteration 0)",
              wave["phase"] == "decided" and int(wave["iteration"]) == 0)
        check("no API call in wave 1", len(adapter.calls) == 0)

        loop = make_loop(config, profile, model_config, adapter,
                         loop_cls=NeverCleanLoop)
        loop.run(max_waves=1)
        wave = loop.load_wave_state()
        check("second invocation completes wave 2",
              wave["phase"] == "decided" and int(wave["iteration"]) == 1)
        check("one API call after wave 2", len(adapter.calls) == 1)


# ---------------------------------------------------------------------------
# Group 9: batch fallback for providers without a batch API
# ---------------------------------------------------------------------------


def test_batch_fallback():
    print("batch fallback (provider without batch API)")

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp)
        config["stages"]["repair"]["api_mode"] = "batch"
        adapter = FakeAdapter(["ok"])

        loop = make_loop(config, profile, model_config, adapter)
        check("openai_compatible falls back to direct", loop.api_mode() == "direct")

        # the fallback must actually drive the loop to completion
        outcome = loop.run()
        check("loop completes via direct fallback", outcome == "done")
        check("API called despite batch config", len(adapter.calls) == 1)

        # forced override keeps batch
        config["stages"]["repair"]["api_mode_overrides"] = {
            "openai_compatible": "batch"
        }
        loop = make_loop(config, profile, model_config, adapter)
        check("forced override keeps batch mode", loop.api_mode() == "batch")


# ---------------------------------------------------------------------------
# Group 10: batch mode state machine (fake batch_api)
# ---------------------------------------------------------------------------


def test_batch_state_machine():
    print("batch mode: submit -> poll(running) -> poll(completed) -> done")

    from thesis.generation import batch_api

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp)
        config["stages"]["repair"]["api_mode_overrides"] = {
            "openai_compatible": "batch"
        }
        adapter = FakeAdapter([])  # must never be called in batch mode

        calls = {"submit": 0, "poll": 0}
        poll_script = ["running", "completed"]

        def fake_submit(provider, model_config, generation_defaults,
                        system_prompt, requests):
            calls["submit"] += 1
            check("batch submit sees the request",
                  len(requests) == 1 and requests[0][0] == sample_id)
            return {"batch_id": "batch_fake_1"}

        def fake_poll(provider, model_config, batch_info):
            calls["poll"] += 1
            state = poll_script.pop(0)
            if state == "running":
                return batch_api.BatchStatus(state="running", detail="in_progress")
            return batch_api.BatchStatus(
                state="completed",
                detail="ended",
                responses={
                    sample_id: batch_api.BatchItemResponse(
                        raw_text=FIXED_ANSWER,
                        finish_reason="stop",
                        truncated=False,
                        response_id="batch-item",
                        usage={"prompt_tokens": 5, "completion_tokens": 3},
                    )
                },
            )

        original = (batch_api.submit_batch, batch_api.poll_batch)
        batch_api.submit_batch, batch_api.poll_batch = fake_submit, fake_poll

        try:
            loop = make_loop(config, profile, model_config, adapter)
            outcome = loop.run()
            check("blocks after batch submit", outcome == "blocked_batch")
            wave = loop.load_wave_state()
            check("phase submitted", wave["phase"] == "submitted")
            check("batch.json persisted with sample order",
                  json.loads(loop.paths.batch_info_path(1).read_text(
                      encoding="utf-8"))["sample_ids"] == [sample_id])

            # restart: still running -> still blocked
            loop = make_loop(config, profile, model_config, adapter)
            check("still blocked while running", loop.run() == "blocked_batch")

            # restart: completed -> merge -> loop finishes
            loop = make_loop(config, profile, model_config, adapter)
            outcome = loop.run()
            check("loop finishes after batch completion", outcome == "done")
            check("final status stopped_clean",
                  loop.sample_states()[sample_id]["status"] == STATUS_CLEAN)

            with loop.paths.iter_generations_path(1).open("r",
                                                          encoding="utf-8") as handle:
                response = json.loads(handle.readline())
            check("batch id on the response record",
                  response.get("repair", {}).get("batch_id") == "batch_fake_1")
            check("batch usage logged",
                  (response.get("api_response") or {}).get("usage", {})
                  .get("prompt_tokens") == 5)

            check("one submit, two polls",
                  calls == {"submit": 1, "poll": 2})
            check("direct adapter never called", len(adapter.calls) == 0)
        finally:
            batch_api.submit_batch, batch_api.poll_batch = original


# ---------------------------------------------------------------------------
# Group 11: external_tools_mode docker (template command execution)
# ---------------------------------------------------------------------------


def test_external_docker_mode():
    print("external_tools_mode docker runs the command template")

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(
            tmp, execution_model="mpi", enable_parcoach=True
        )

        # Template stands in for the docker command: a script that merges
        # parcoach entries into the iteration's static_analysis.jsonl —
        # exactly what the containerized runner would do.
        script = Path(tmp) / "fake_external.py"
        script.write_text(
            "import json, sys\n"
            "path = sys.argv[1]\n"
            "records = [json.loads(l) for l in open(path) if l.strip()]\n"
            "for r in records:\n"
            "    r['tools']['parcoach'] = {'tool': 'parcoach', 'ran': True,\n"
            "                              'findings': []}\n"
            "open(path, 'w').write(''.join(json.dumps(r) + '\\n'\n"
            "                              for r in records))\n",
            encoding="utf-8",
        )
        intermediate = Path(tmp) / "intermediate"
        config["stages"]["repair"]["external_tools_mode"] = "docker"
        config["stages"]["repair"]["external_tool_commands"] = {
            "parcoach": '%s "%s" "%s/{run_id}/{model_id}/static_analysis.jsonl"'
            % (sys.executable, script.as_posix(), intermediate.as_posix())
        }

        adapter = FakeAdapter([])
        loop = make_loop(config, profile, model_config, adapter)
        outcome = loop.step()
        check("docker mode advances without waiting", outcome == "advanced")
        check("phase analyzed", loop.load_wave_state()["phase"] == "analyzed")
        check("no pending file in docker mode",
              not loop.paths.pending_external_path.exists())

        records = loop.load_stage_records(0, "static_analysis")
        check("parcoach records merged by the template command",
              "parcoach" in records[sample_id]["tools"])

        # missing template is a hard error (fail loudly, not silently)
        config["stages"]["repair"]["external_tool_commands"] = {}
        # force re-analysis waiting: drop parcoach entries again
        for record in records.values():
            record["tools"].pop("parcoach", None)
        static_path = loop.paths.stage_path(0, "static_analysis")
        static_path.write_text(
            "".join(json.dumps(r) + "\n" for r in records.values()),
            encoding="utf-8",
        )
        loop = make_loop(config, profile, model_config, adapter)
        try:
            loop._to_analyzed(0)
            check("missing docker template raises", False)
        except ValueError:
            check("missing docker template raises", True)

        # A FAILING container run must NOT advance the wave: the findings
        # never arrived, so deciding the sample now would score it as clean.
        config["stages"]["repair"]["external_tool_commands"] = {
            "parcoach": '%s -c "import sys; sys.exit(3)"' % sys.executable
        }
        loop = make_loop(config, profile, model_config, adapter)
        outcome = loop._to_analyzed(0)

        check("failing container -> blocked_external",
              outcome == "blocked_external")
        check("wave stays in analyzed_waiting_external",
              loop.load_wave_state()["phase"] == "analyzed_waiting_external")
        check("pending file written so the wave is resumable",
              loop.paths.pending_external_path.exists()
              and "parcoach" in loop.paths.pending_external_path.read_text(
                  encoding="utf-8"))
        check("sample NOT decided as clean",
              loop.sample_states().get(sample_id) is None)

        # a container that exits 0 but writes nothing is the same situation
        config["stages"]["repair"]["external_tool_commands"] = {
            "parcoach": '%s -c "pass"' % sys.executable
        }
        loop = make_loop(config, profile, model_config, adapter)
        check("silent no-op container also blocks",
              loop._to_analyzed(0) == "blocked_external")

        # host_repo placeholder resolution (docker-outside-of-docker)
        settings = dict(loop.settings)
        settings["external_tool_commands"] = {"parcoach": "run {host_repo} {repo}"}
        settings["host_repo_path"] = "C:/host/repo"
        command = orchestrator.build_external_command(
            settings, "cfg.yaml", "unit", "run_x", "m", "parcoach"
        )
        check("host_repo placeholder filled from config",
              command.startswith("run C:/host/repo "))


# ---------------------------------------------------------------------------


def main():
    tests = [
        test_stop_logic,
        test_grace_once,
        test_full_wave_with_resume,
        test_dry_run_history_modes,
        test_transport_retry,
        test_refusal_unusable,
        test_external_waiting,
        test_budget_stop,
        test_max_wave,
        test_batch_fallback,
        test_batch_state_machine,
        test_external_docker_mode,
    ]

    for test in tests:
        test()
        print()

    if FAILURES:
        print("FAILED (%d):" % len(FAILURES))
        for label in FAILURES:
            print("  - " + label)
        sys.exit(1)

    print("All %d orchestrator test groups passed." % len(tests))


if __name__ == "__main__":
    main()
