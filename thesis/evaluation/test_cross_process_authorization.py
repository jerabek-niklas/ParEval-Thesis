"""Cross-process run authorization: bootstrap and rehydration.

THE DEFECT THIS SUITE FIXES AND GUARDS

The run authorization context lives in `run_authorization._CONTEXT`, which is
process-local. The productive generation orchestrator starts every provider
runner as a NEW process:

    generate.py -> subprocess -> generate-<provider>.py
                -> common.run_generation(...) -> adapter.generate(...)
                -> common.call_with_retries(...) -> require_provider_call(...)

Python RAM does not cross that boundary. A child of an authorized parent
therefore saw NO context and the direct chokepoint refused its first request,
although a valid authorization was persisted for the run. The same held for a
later, independent batch poll / resume process and for the repair loop.

    PERSISTENT RUN PROVENANCE IS AUTHORITATIVE;
    THE PROCESS CONTEXT IS ONLY A VALIDATED CACHE.

The chokepoints are NOT weakened: `require_provider_call` still refuses
whenever no valid context is installed (proved here by a worker that skips the
bootstrap), and it never falls back to reading a file with implicit defaults.
Productive processes install a context that was VALIDATED against the
persisted provenance instead.

Every provider interaction is a MOCK. The tests replace the private provider
helpers BELOW the chokepoints (batch_api._anthropic_submit / _poll) or hand a
mock `fn` to call_with_retries, so the real dispatchers - and therefore the
real guards - execute. No real OpenAI/Anthropic/Gemini/DashScope request is
made (API calls: 0).

Two fixture injections happen INSIDE a child process (never in production
code, never via a CLI):

    check_static_repair_readiness.measure_runtime  -> fake environments,
        counted, so "a pure poll performs no fresh runtime probe" is measured
        rather than asserted;
    run_authorization.authorize_start              -> allow_draft_contract,
        because the repository contract is legitimately NOT_READY while the
        pilot_002 population decision is open.

Run:  python thesis/evaluation/test_cross_process_authorization.py
      python thesis/evaluation/test_cross_process_authorization.py --worker ...
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import manifest_fragments as mf  # noqa: E402
from thesis.evaluation import pilot_run_contract as prc  # noqa: E402
from thesis.evaluation import run_authorization as ra  # noqa: E402
from thesis.evaluation.test_post_run_verification import (  # noqa: E402
    fake_environments, fake_prober, write_readiness_artifact)

FAILURES = []

PROMPT_TEXT = ("#include <vector>\n/* fixture prompt */\n"
               "void relu(std::vector<double> &x) {")
PROMPT_TEXT2 = ("#include <vector>\n/* fixture prompt 2 */\n"
                "int xorOf(std::vector<int> const& x) {")
API_KEY_ENV = "PAREVAL_XPROC_KEY"


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# fixture: a minimal, contract-conform generation run
# ---------------------------------------------------------------------------

class ProviderWorld:
    """A generation run on disk: config, prompts, its own readiness proof and
    a frozen contract at the CANONICAL per-run location - exactly what a
    fresh provider process must be able to find on its own."""

    def __init__(self, root, run_id="pilot_002_xproc", provider="mock",
                 api_mode="direct", model_id="mock_model"):
        self.root = Path(root)
        self.run_id = run_id
        self.provider = provider
        self.api_mode = api_mode
        self.model_id = model_id
        self.config_path = self.root / "config.yaml"
        self.prompts_path = self.root / "prompts.json"
        self.readiness_path = self.root / "readiness.json"
        self._write_prompts()
        self._write_config()
        from thesis.config.load_config import load_config

        self.config = load_config(self.config_path)
        write_readiness_artifact(self.config, self.readiness_path)
        self.contract = prc.build_contract(self.config_path, "fixture", self.run_id)
        self.contract_path = ra.canonical_contract_path(self.config, self.run_id)
        self.contract_sha = prc.freeze_contract(self.contract, self.contract_path,
                                                allow_draft=True)

    def _write_prompts(self):
        atomic_io.atomic_write_json(self.prompts_path, [
            {"problem_type": "transform", "name": "55_transform_relu", "language": "cpp",
             "parallelism_model": "serial", "prompt": PROMPT_TEXT},
            {"problem_type": "reduce", "name": "25_reduce_xor", "language": "cpp",
             "parallelism_model": "serial", "prompt": PROMPT_TEXT2},
        ])

    def _write_config(self):
        config = {
            "outputs": {"raw_dir": (self.root / "raw").as_posix(),
                        "intermediate_dir": (self.root / "intermediate").as_posix(),
                        "root": (self.root / "results").as_posix(),
                        "readiness_artifact": self.readiness_path.as_posix()},
            "prompts": {"path": self.prompts_path.as_posix(), "prompt_field": "prompt",
                        "execution_models": ["serial"], "problem_types": None},
            "profiles": {"fixture": {"run_id": self.run_id, "selection": "prefix",
                                     "prompt_limit": 2, "num_samples_per_prompt": 1}},
            "models": [{"id": self.model_id, "enabled": True, "provider": self.provider,
                        "model_name": "mock-1", "api_key_env": API_KEY_ENV}],
            "generation_defaults": {"timeout_seconds": 300, "retry_attempts": 0,
                                    "system_prompt": "fixture system prompt",
                                    "max_output_tokens": 128, "api_mode": self.api_mode},
            "stages": {
                "assembly": {"enabled": True, "auto_close_single_brace": True,
                             "output_file_name": "assembly.jsonl"},
                "correctness_tests": {"enabled": True, "niter": 1,
                                      "run_timeout_seconds": 120,
                                      "output_file_name": "correctness.jsonl"},
                "static_analysis": {"enabled": True, "tools": {
                    "compiler": {"enabled": True}, "clang_tidy": {"enabled": False},
                    "gcc_analyzer": {"enabled": False}, "cppcheck": {"enabled": False},
                    "infer": {"enabled": False}, "parcoach": {"enabled": False},
                    "llov": {"enabled": False}}},
                "dynamic_analysis": {"enabled": False, "tools": {}},
                "enhanced_tests": {"enabled": False, "execution_models": ["serial"]},
                "repair": {"enabled": False},
            },
        }
        self.config_path.write_text(yaml.safe_dump(config, sort_keys=False),
                                    encoding="utf-8")

    # ---- helpers -------------------------------------------------------
    def authorize(self, prober=fake_prober):
        """Pre-authorize IN THIS PROCESS, so the child has to rehydrate."""
        ra.clear_context()
        authorization = ra.authorize_start(self.config, self.config_path, "fixture",
                                           self.run_id, self.contract_path,
                                           prober=prober, allow_draft_contract=True)
        ra.clear_context()
        return authorization

    def stored_authorization(self):
        return ra.load_authorization(self.config, self.run_id)

    def authorization_fragments(self):
        directory = mf.fragments_dir(Path(self.config["outputs"]["intermediate_dir"]),
                                     self.run_id)
        if not directory.is_dir():
            return []
        return sorted(p.name for p in directory.glob("authorization*.json"))

    def out_dir(self):
        return Path(self.config["outputs"]["raw_dir"]) / self.run_id / self.model_id

    def drift_contract(self):
        """A methodical config change after the freeze."""
        config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        config["generation_defaults"]["timeout_seconds"] = 999
        self.config_path.write_text(yaml.safe_dump(config, sort_keys=False),
                                    encoding="utf-8")

    def tamper_authorization(self, field="fresh_t0_runtime_condition_sha256",
                             value="0" * 64):
        path = mf.fragment_path(Path(self.config["outputs"]["intermediate_dir"]),
                                self.run_id, ra.AUTHORIZATION_FRAGMENT_KIND,
                                ra.AUTHORIZATION_FRAGMENT_OWNER)
        fragment = json.loads(path.read_text(encoding="utf-8"))
        fragment["content"][field] = value
        atomic_io.atomic_write_json(path, fragment)
        mf.write_snapshot(Path(self.config["outputs"]["intermediate_dir"]), self.run_id)

    def damage_provenance(self, kind):
        """Break the run provenance the way real corruption does - outside the
        authorization fragment, where the failure used to escape unclassified."""
        directory = mf.fragments_dir(Path(self.config["outputs"]["intermediate_dir"]),
                                     self.run_id)
        sibling = next((p for p in sorted(directory.glob("*.json"))
                        if p.name != "authorization.start.json"), None)
        if kind == "torn_contract":
            text = self.contract_path.read_text(encoding="utf-8")
            self.contract_path.write_text(text[:len(text) // 2], encoding="utf-8")
            return
        assert sibling is not None, "the fixture has no sibling fragment to damage"
        if kind == "torn":
            text = sibling.read_text(encoding="utf-8")
            sibling.write_text(text[:len(text) // 2], encoding="utf-8")
        elif kind == "foreign_run":
            fragment = json.loads(sibling.read_text(encoding="utf-8"))
            fragment["run_id"] = "some_other_run"
            atomic_io.atomic_write_json(sibling, fragment)
        elif kind == "null_content":
            fragment = json.loads(sibling.read_text(encoding="utf-8"))
            fragment["content"] = None
            atomic_io.atomic_write_json(sibling, fragment)
        else:  # pragma: no cover - programming error in the fixture
            raise ValueError("unknown damage kind %r" % kind)

    def tamper_t0_evidence(self, field="fresh_runtime_condition_sha256", value="1" * 64):
        path = mf.fragment_path(Path(self.config["outputs"]["intermediate_dir"]),
                                self.run_id, "runtime", "evidence")
        fragment = json.loads(path.read_text(encoding="utf-8"))
        fragment["content"][field] = value
        atomic_io.atomic_write_json(path, fragment)
        mf.write_snapshot(Path(self.config["outputs"]["intermediate_dir"]), self.run_id)


# ---------------------------------------------------------------------------
# child process workers - the productive path, mocked only below the provider
# ---------------------------------------------------------------------------

PROBES = {"n": 0}


def _install_fixture_probe(drift=False, allow_draft=True):
    """Fake the docker probe (never the authorization logic) and count it."""
    from thesis.evaluation import check_static_repair_readiness as csrr

    def measure(config):
        PROBES["n"] += 1
        environments = fake_environments()
        if drift:
            environments["main"]["image_id"] = "sha256:" + "d" * 64
        return environments

    csrr.measure_runtime = measure
    if allow_draft:
        # the repository contract is legitimately NOT_READY while the pilot_002
        # population decision is open; a first start in a fixture may use a
        # draft. `--worker direct_strict` deliberately does NOT patch this, so
        # the productive allow_draft_contract=False gate stays under test.
        ra.authorize_start = functools.partial(ra.authorize_start,
                                               allow_draft_contract=True)


class MockAdapter:
    """The seam a real provider script occupies: its generate() hands the SDK
    call to the productive direct chokepoint, exactly like the four real
    adapters do."""

    provider = "mock"
    default_api_key_env = API_KEY_ENV

    def create_client(self, model_config, api_key, timeout_seconds=None):
        return object()

    def generation_parameters(self, model_config, generation_defaults):
        return {"max_output_tokens": 128}

    def generate(self, client, model_config, generation_defaults, system_prompt,
                 messages, retry_attempts, sleep_seconds):
        from thesis.generation import common

        def provider_call():
            print("MOCK_PROVIDER_REACHED")
            return object()

        common.call_with_retries(fn=provider_call, retry_attempts=0, sleep_seconds=0,
                                 label="mock direct")
        return common.GenerationResult(
            raw_text="```cpp\nvoid relu(std::vector<double> &x) {}\n```",
            finish_reason="stop", truncated=False, response_id="mock-1", usage={})


class AnthropicMockAdapter(MockAdapter):
    """Batch mode never calls generate(); the provider decides which private
    submit/poll helper the REAL dispatcher reaches."""

    provider = "anthropic"


def worker_main(argv) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", default="fixture")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--model-id", default="mock_model")
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--drift-runtime", action="store_true")
    parser.add_argument("--hammer", type=int, default=120)
    args = parser.parse_args(argv)

    from thesis.config.load_config import load_config
    from thesis.generation import batch_api, common

    print("CHILD_PID=%d" % os.getpid())
    print("CHILD_CONTEXT_AT_START=%s" % ("PRESENT" if ra.current_context() else "NONE"))
    _install_fixture_probe(drift=args.drift_runtime,
                           allow_draft=args.worker != "direct_strict")
    if args.worker == "direct_strict":
        args.worker = "direct"
    config = load_config(Path(args.config))
    run_id = args.run_id or config["profiles"][args.profile]["run_id"]

    if args.worker == "lock_hammer":
        # The registration lock under real multi-process contention on ONE key.
        # On Windows a concurrent mkdir/rmdir of the same lock directory fails
        # with a sharing violation (WinError 5/32), NOT FileExistsError; an
        # unretried escape would be an unclassified PermissionError in the
        # middle of a per-model pilot start.
        from thesis.evaluation import effective_invocation as ei
        from thesis.evaluation import manifest_fragments as mf

        # a REAL invocation payload, so the post-run integrity check can
        # recompute its fingerprint afterwards
        payload = ei.build_invocation(
            run_id, "correctness", "fixture",
            {"primary_compiler": {"value": "g++", "source": "DEFAULT"}})
        escapes = 0
        for index in range(int(args.hammer)):
            try:
                mf.register_fragment(
                    Path(config["outputs"]["intermediate_dir"]), run_id, "invocation",
                    "hammer", payload,
                    fingerprint=payload["invocation_sha256"], writer="hammer")
            except mf.FragmentConflict:
                pass  # a classified conflict is a legitimate outcome
            except Exception as error:  # noqa: BLE001
                escapes += 1
                print("ESCAPE %s: %s" % (type(error).__name__, error))
        print("ESCAPES=%d" % escapes)
        print("RESULT=OK")
        return 0

    if args.worker == "no_bootstrap":
        # the chokepoint must stay fail-closed for a process that installs no
        # validated context: this is the defect's permanent regression fixture
        try:
            common.call_with_retries(fn=lambda: print("MOCK_PROVIDER_REACHED"),
                                     retry_attempts=0, sleep_seconds=0, label="unguarded")
            print("RESULT=REACHED_WITHOUT_BOOTSTRAP")
        except ra.ProviderCallRefused as refusal:
            print("RESULT=REFUSED %s" % refusal)
        return 0

    if args.worker == "repair":
        # the productive repair entry point's bootstrap, with a stub loop that
        # carries exactly what it reads: config and the base run id
        from thesis.repair import run_repair

        class _Paths:
            base_run_id = run_id

        class _Loop:
            pass

        loop = _Loop()
        loop.config = config
        loop.paths = _Paths()
        stub_args = argparse.Namespace(config=args.config, profile=args.profile,
                                       poll=args.poll)
        try:
            run_repair.bootstrap_run_authorization(stub_args, [loop])
        except ra.PreRunInfrastructureFailure as failure:
            print("RESULT=REFUSED %s: %s" % (type(failure).__name__, failure))
            return ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
        context = ra.current_context() or {}
        print("AUTH_SHA=%s" % context.get("authorization_sha256"))
        print("PROBES_AFTER_BOOTSTRAP=%d" % PROBES["n"])
        reached = {"direct": False, "batch": False}
        try:
            common.call_with_retries(fn=lambda: reached.__setitem__("direct", True),
                                     retry_attempts=0, sleep_seconds=0, label="repair direct")
        except ra.PreRunInfrastructureFailure as failure:
            print("RESULT=DIRECT_REFUSED %s" % failure)
            return ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
        original = batch_api._anthropic_submit
        batch_api._anthropic_submit = lambda *a, **k: reached.__setitem__("batch", True) or {
            "batch_id": "repair-job-1"}
        try:
            batch_api.submit_batch(provider="anthropic", model_config={},
                                   generation_defaults={}, system_prompt="",
                                   requests=[("s", "t")])
        except ra.PreRunInfrastructureFailure as failure:
            print("RESULT=BATCH_REFUSED %s" % failure)
            return ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
        finally:
            batch_api._anthropic_submit = original
        print("REPAIR_DIRECT_REACHED=%s" % reached["direct"])
        print("REPAIR_BATCH_REACHED=%s" % reached["batch"])
        print("PROBES=%d" % PROBES["n"])
        print("RESULT=OK")
        return 0

    # ---- generation workers (the real runner entry point) ------------------
    adapter = AnthropicMockAdapter() if args.worker.startswith("batch") else MockAdapter()
    if args.worker.startswith("batch"):
        def fake_submit(model_config, generation_defaults, system_prompt, requests, **kw):
            print("MOCK_SUBMIT_REACHED %d" % len(requests))
            return {"batch_id": "job-1"}

        def fake_poll(model_config, batch_info):
            print("MOCK_POLL_REACHED")
            sample_ids = list(batch_info["sample_ids"])
            if args.worker == "batch_poll_partial":
                # ONE request comes back without a response: the REAL
                # BatchResponseMissing bookkeeping path
                sample_ids = sample_ids[:1]
            responses = {sample_id: batch_api.BatchItemResponse(
                raw_text="```cpp\nvoid relu(std::vector<double> &x) {}\n```",
                finish_reason="completed", truncated=False, response_id="r-1",
                usage={"input_tokens": 5, "output_tokens": 7})
                for sample_id in sample_ids}
            return batch_api.BatchStatus(state="completed", detail="completed",
                                         responses=responses)

        batch_api._anthropic_submit = fake_submit
        batch_api._anthropic_poll = fake_poll

    os.environ[API_KEY_ENV] = "fixture-not-a-real-key"
    sys.argv = (["generate-mock.py", "--config", args.config, "--profile", args.profile,
                 "--model-id", args.model_id]
                + (["--poll"] if args.poll else [])
                + (["--restart"] if args.restart else []))
    try:
        common.run_generation(adapter)
    except SystemExit as exit_:
        code = int(exit_.code or 0)
        print("PROBES=%d" % PROBES["n"])
        print("RESULT=EXIT_%d" % code)
        return code
    context = ra.current_context() or {}
    print("AUTH_SHA=%s" % context.get("authorization_sha256"))
    print("HYDRATED=%s" % context.get("hydrated_from_persistent_provenance"))
    print("PROBES=%d" % PROBES["n"])
    print("RESULT=OK")
    return 0


def spawn(world, worker, extra=(), wait=True):
    command = [sys.executable, __file__, "--worker", worker,
               "--config", str(world.config_path), "--profile", "fixture",
               "--run-id", world.run_id, "--model-id", world.model_id] + list(extra)
    env = dict(os.environ)
    env[API_KEY_ENV] = "fixture-not-a-real-key"
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, cwd=str(REPO_ROOT), env=env)
    if not wait:
        return process
    out, _ = process.communicate()
    return OrderedDict([("rc", process.returncode), ("out", out)])


def marker(out, key, default=None):
    for line in (out or "").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


# ---------------------------------------------------------------------------
# 1. the defect itself
# ---------------------------------------------------------------------------

def test_defect_is_real():
    print("== the cross-process defect (regression fixture) ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        authorization = world.authorize()
        result = spawn(world, "no_bootstrap")
        check("a child process starts with NO authorization context",
              marker(result["out"], "CHILD_CONTEXT_AT_START") == "NONE")
        check("the persisted authorization is valid and START_ALLOWED",
              (world.stored_authorization() or {}).get("decision") == ra.DECISION_ALLOWED)
        check("a child that installs no validated context is REFUSED at the chokepoint",
              str(marker(result["out"], "RESULT", "")).startswith("REFUSED"))
        check("the mock provider was never reached without a bootstrap",
              "MOCK_PROVIDER_REACHED" not in result["out"])
        check("the chokepoint refusal names the pre-run infrastructure failure",
              "PRE_RUN_INFRASTRUCTURE_FAILURE" in result["out"])
        check("the parent's authorization is unaffected by the refused child",
              (world.stored_authorization() or {}).get("authorization_sha256")
              == authorization["authorization_sha256"])


# ---------------------------------------------------------------------------
# 2. first start and rehydration in a real provider child process
# ---------------------------------------------------------------------------

def test_first_start_child():
    print("== a provider child process authorizes a NEW run itself ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        check("no authorization exists before the child runs",
              world.stored_authorization() is None)
        result = spawn(world, "direct")
        check("the child reached the mock provider", "MOCK_PROVIDER_REACHED" in result["out"])
        check("the child performed the FIRST START itself",
              "FIRST_START" in result["out"])
        check("the child found the contract at the canonical run location",
              "canonical_run_location" in result["out"])
        stored = world.stored_authorization() or {}
        check("exactly one canonical authorization was persisted",
              world.authorization_fragments() == ["authorization.start.json"])
        check("the persisted authorization is START_ALLOWED",
              stored.get("decision") == ra.DECISION_ALLOWED)
        check("the child's authorization sha equals the persisted one",
              marker(result["out"], "AUTH_SHA") == stored.get("authorization_sha256"))
        check("no parent RAM context was required", result["rc"] == 0)

    with tempfile.TemporaryDirectory() as tmp:
        # the productive gate: a NOT_READY contract may never authorize a
        # cost-causing run. The fixture contract IS a draft (the pilot_002
        # population decision is open), so a child that does not carry the
        # fixture's allow_draft injection must be refused.
        world = ProviderWorld(Path(tmp))
        result = spawn(world, "direct_strict")
        check("a NOT_READY (draft) contract cannot authorize a first start",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and "the contract is NOT_READY" in result["out"])
        check("the refused draft start wrote no authorization and reached no provider",
              world.stored_authorization() is None
              and "MOCK_PROVIDER_REACHED" not in result["out"])


def test_rehydration_child():
    print("== a later provider child process REHYDRATES the existing run ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        authorization = world.authorize()
        before = world.authorization_fragments()
        result = spawn(world, "direct")
        check("the child rehydrated instead of authorizing again",
              ra.MODE_REHYDRATED in result["out"])
        check("the child reached the mock provider",
              "MOCK_PROVIDER_REACHED" in result["out"])
        check("the rehydrated context is marked as persisted provenance",
              marker(result["out"], "HYDRATED") == "True")
        check("the rehydrated authorization sha is the SAME",
              marker(result["out"], "AUTH_SHA")
              == authorization["authorization_sha256"])
        check("no second authorization fragment was written",
              world.authorization_fragments() == before)
        check("the rehydration performed no fresh runtime probe",
              marker(result["out"], "PROBES") == "0")
        check("rehydration validates the full identity chain, not file existence",
              set(ra.REHYDRATION_CHECKS) >= {
                  "authorization_fingerprint_exact", "run_id_exact",
                  "contract_bound_to_run_exact", "t0_runtime_evidence_present",
                  "authorization_runtime_sha_equals_t0",
                  "live_contract_rebuild_without_drift"})


def test_tampered_and_drifted_children():
    print("== a child refuses tampered provenance and drift ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        world.authorize()
        world.tamper_authorization()
        result = spawn(world, "direct")
        check("tampered authorization -> REFUSED",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE)
        check("tampered authorization -> mock provider never reached",
              "MOCK_PROVIDER_REACHED" not in result["out"])

    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        world.authorize()
        world.tamper_t0_evidence()
        result = spawn(world, "direct")
        check("tampered T0 runtime evidence -> REFUSED",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE)
        check("tampered T0 evidence -> mock provider never reached",
              "MOCK_PROVIDER_REACHED" not in result["out"])

    # every way the run provenance layer can break must be CLASSIFIED: an
    # unclassified traceback would leave the runner at exit 1, which the
    # orchestrator skips under --continue-on-error as an ordinary model failure
    for damage, label in (("torn", "a torn (truncated) sibling fragment"),
                          ("foreign_run", "a sibling fragment of ANOTHER run"),
                          ("null_content", "a sibling fragment without content"),
                          ("torn_contract", "a corrupt frozen contract file")):
        with tempfile.TemporaryDirectory() as tmp:
            world = ProviderWorld(Path(tmp))
            world.authorize()
            world.damage_provenance(damage)
            result = spawn(world, "direct")
            check("%s -> CLASSIFIED refusal (exit %d), never a bare traceback"
                  % (label, ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE),
                  result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
                  and "PRE_RUN_INFRASTRUCTURE_FAILURE" in result["out"]
                  and "Traceback" not in result["out"])
            check("%s -> mock provider never reached" % label,
                  "MOCK_PROVIDER_REACHED" not in result["out"])

    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        world.authorize()
        world.drift_contract()
        result = spawn(world, "direct")
        check("contract drift during rehydration -> REFUSED",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and "contract drift" in result["out"])
        check("contract drift -> mock provider never reached",
              "MOCK_PROVIDER_REACHED" not in result["out"])

    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp), api_mode="batch", provider="anthropic")
        world.authorize()
        result = spawn(world, "batch_submit", extra=["--drift-runtime"])
        check("runtime drift before a NEW batch submission -> REFUSED",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE)
        check("runtime drift -> the mock submit was never reached",
              "MOCK_SUBMIT_REACHED" not in result["out"])

    with tempfile.TemporaryDirectory() as tmp:
        # a DIRECT first start probes the runtime itself, so a drifted runtime
        # is refused before the first request. (For a rehydrated direct call
        # the unchanged wave-1 chokepoint policy is authorization_readback +
        # contract_rebuild - only a NEW cost-causing BATCH submission
        # re-probes; drift during the measurement stages is caught by the
        # per-stage runtime binding.)
        world = ProviderWorld(Path(tmp))
        result = spawn(world, "direct", extra=["--drift-runtime"])
        check("runtime drift at a DIRECT first start -> REFUSED",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and "runtime drift since the readiness proof" in result["out"])
        check("the drifted direct start reached no provider and wrote no authorization",
              "MOCK_PROVIDER_REACHED" not in result["out"]
              and world.stored_authorization() is None)
        check("the direct revalidation policy is unchanged (wave 1 chokepoint "
              "definition)",
              ra.REVALIDATION_POLICY[ra.CALL_KIND_DIRECT]
              == ("authorization_readback", "contract_rebuild")
              and "fresh_runtime" in ra.REVALIDATION_POLICY[ra.CALL_KIND_BATCH_SUBMIT])


# ---------------------------------------------------------------------------
# 3. batch: submit, poll and the real resubmission - three separate processes
# ---------------------------------------------------------------------------

def test_batch_processes():
    print("== batch submit, poll and resubmission across separate processes ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp), api_mode="batch", provider="anthropic")
        world.authorize()
        before = world.authorization_fragments()

        submit = spawn(world, "batch_submit")
        check("PROCESS 1 (submit) rehydrated and reached the mock submit",
              ra.MODE_REHYDRATED in submit["out"]
              and "MOCK_SUBMIT_REACHED 2" in submit["out"])
        check("PROCESS 1 wrote the batch bookkeeping",
              (world.out_dir() / "generation_batch.json").is_file())

        poll = spawn(world, "batch_poll", extra=["--poll"])
        check("PROCESS 2 (poll) rehydrated the authorization in a fresh process",
              ra.MODE_REHYDRATED in poll["out"])
        check("PROCESS 2 reached the mock poll", "MOCK_POLL_REACHED" in poll["out"])
        check("a pure poll performs NO fresh runtime probe",
              marker(poll["out"], "PROBES") == "0")
        check("a pure poll creates NO new authorization",
              world.authorization_fragments() == before)
        check("a pure poll starts no new provider job",
              "MOCK_SUBMIT_REACHED" not in poll["out"])
        check("the poll consumed the bookkeeping (renamed to .done.json)",
              (world.out_dir() / "generation_batch.done.json").is_file()
              and not (world.out_dir() / "generation_batch.json").is_file())


def test_cross_process_resubmission():
    print("== the REAL BatchResponseMissing resubmission in a THIRD process ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp), api_mode="batch", provider="anthropic")
        world.authorize()
        spawn(world, "batch_submit")
        # a poll that returns only ONE of the two responses: the real
        # BatchResponseMissing bookkeeping path
        poll = spawn(world, "batch_poll_partial", extra=["--poll"])
        check("the partial poll consumed the bookkeeping",
              (world.out_dir() / "generation_batch.done.json").is_file())
        check("the partial poll reached the mock poll", "MOCK_POLL_REACHED" in poll["out"])

        resubmit = spawn(world, "batch_submit")
        check("PROCESS 3 (resubmit) rehydrated the authorization",
              ra.MODE_REHYDRATED in resubmit["out"])
        check("the real resubmission reached the mock submit with the missing request",
              "MOCK_SUBMIT_REACHED 1" in resubmit["out"])

        # contract drift before the cross-process resubmit
        (world.out_dir() / "generation_batch.json").unlink(missing_ok=True)
        original = world.config_path.read_text(encoding="utf-8")
        world.drift_contract()
        drifted = spawn(world, "batch_submit")
        check("contract drift before a cross-process resubmit -> REFUSED",
              drifted["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and "MOCK_SUBMIT_REACHED" not in drifted["out"])
        world.config_path.write_text(original, encoding="utf-8")

        # runtime drift before the cross-process resubmit
        (world.out_dir() / "generation_batch.json").unlink(missing_ok=True)
        runtime_drift = spawn(world, "batch_submit", extra=["--drift-runtime"])
        check("runtime drift before a cross-process resubmit -> REFUSED",
              runtime_drift["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and "MOCK_SUBMIT_REACHED" not in runtime_drift["out"])


# ---------------------------------------------------------------------------
# 4. concurrent model processes
# ---------------------------------------------------------------------------

def test_concurrent_children():
    print("== N concurrent provider child processes for the same run ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        processes = [spawn(world, "direct", wait=False) for _ in range(4)]
        outputs = []
        for process in processes:
            out, _ = process.communicate()
            outputs.append((process.returncode, out))
        shas = {marker(out, "AUTH_SHA") for rc, out in outputs if rc == 0}
        check("A: every concurrent first-start child succeeded",
              all(rc == 0 for rc, _ in outputs))
        check("A: exactly ONE canonical authorization exists",
              world.authorization_fragments() == ["authorization.start.json"])
        check("A: all children agree on ONE authorization sha", len(shas) == 1)
        check("A: no contradicting authorization was written",
              shas == {(world.stored_authorization() or {}).get("authorization_sha256")})
        check("A: every child reached the mock provider",
              all("MOCK_PROVIDER_REACHED" in out for _, out in outputs))
        check("A: no child needed a parent RAM context",
              all(marker(out, "CHILD_CONTEXT_AT_START") == "NONE" for _, out in outputs))

    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        authorization = world.authorize()
        processes = [spawn(world, "direct", wait=False) for _ in range(4)]
        outputs = []
        for process in processes:
            out, _ = process.communicate()
            outputs.append((process.returncode, out))
        check("B: every child rehydrated the existing authorization",
              all(rc == 0 and ra.MODE_REHYDRATED in out for rc, out in outputs))
        check("B: 0 new authorizations",
              world.authorization_fragments() == ["authorization.start.json"]
              and (world.stored_authorization() or {}).get("authorization_sha256")
              == authorization["authorization_sha256"])
        check("B: all rehydrations see the SAME authorization sha",
              {marker(out, "AUTH_SHA") for _, out in outputs}
              == {authorization["authorization_sha256"]})


# ---------------------------------------------------------------------------
# 5. repair in its own process
# ---------------------------------------------------------------------------

def test_registration_lock_under_contention():
    print("== the registration lock survives real multi-process contention ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        world.authorize()
        processes = [spawn(world, "lock_hammer", extra=["--hammer", "120"], wait=False)
                     for _ in range(6)]
        outputs = []
        for process in processes:
            out, _ = process.communicate()
            outputs.append((process.returncode, out))
        escapes = sum(int(marker(out, "ESCAPES") or 0) for _, out in outputs)
        print("   6 processes x 120 registrations on ONE key -> %d unclassified escape(s)"
              % escapes)
        check("6 concurrent writers on one fragment key: 0 unclassified escapes",
              escapes == 0 and all(rc == 0 for rc, _ in outputs))
        check("the fragment survived the contention intact",
              not mf.verify_fragment_integrity(
                  Path(world.config["outputs"]["intermediate_dir"]), world.run_id))


def test_repair_process():
    print("== the repair loop bootstraps in its own process ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp), provider="anthropic")
        authorization = world.authorize()
        result = spawn(world, "repair")
        check("the repair process rehydrated the authorization",
              ra.MODE_REHYDRATED in result["out"]
              and marker(result["out"], "AUTH_SHA")
              == authorization["authorization_sha256"])
        check("the repair DIRECT provider call is allowed after the bootstrap",
              marker(result["out"], "REPAIR_DIRECT_REACHED") == "True")
        check("the repair BATCH submit is allowed after the bootstrap",
              marker(result["out"], "REPAIR_BATCH_REACHED") == "True")
        check("the repair REHYDRATION itself performed no fresh runtime probe",
              marker(result["out"], "PROBES_AFTER_BOOTSTRAP") == "0")
        check("a NEW repair batch submission DOES revalidate the runtime "
              "(REVALIDATION_POLICY)",
              int(marker(result["out"], "PROBES") or 0) == 1
              and "fresh_runtime" in ra.REVALIDATION_POLICY[ra.CALL_KIND_BATCH_SUBMIT])

    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp), provider="anthropic")
        world.authorize()
        world.drift_contract()
        result = spawn(world, "repair")
        check("repair + contract drift -> REFUSED",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE)
        check("repair + drift -> no provider mock reached",
              "REPAIR_DIRECT_REACHED" not in result["out"])

    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp), provider="anthropic")
        world.authorize()
        world.tamper_authorization()
        result = spawn(world, "repair")
        check("repair + tampered authorization -> REFUSED",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE)


# ---------------------------------------------------------------------------
# 6. orchestrator semantics: dry-run and continue-on-error
# ---------------------------------------------------------------------------

def test_dry_run_authorizes_nothing():
    print("== --dry-run authorizes nothing and probes nothing ==")
    from thesis.generation import generate

    with tempfile.TemporaryDirectory() as tmp:
        # a provider the orchestrator knows, so it builds a real child command
        world = ProviderWorld(Path(tmp), provider="anthropic")
        probes = {"n": 0}
        spawned = []
        original_run, original_measure = generate.run_command, None
        from thesis.evaluation import check_static_repair_readiness as csrr

        original_measure = csrr.measure_runtime

        def counting(config):
            probes["n"] += 1
            return fake_environments()

        def recording(command, dry_run):
            spawned.append(command)
            return original_run(command, dry_run)

        csrr.measure_runtime = counting
        generate.run_command = recording
        argv = sys.argv
        sys.argv = ["generate.py", "--config", str(world.config_path),
                    "--profile", "fixture", "--dry-run"]
        try:
            generate.main()
        finally:
            sys.argv = argv
            generate.run_command = original_run
            csrr.measure_runtime = original_measure
        check("dry-run writes NO authorization", world.stored_authorization() is None)
        check("dry-run performs NO runtime probe", probes["n"] == 0)
        check("dry-run starts no provider process (it only prints the command)",
              len(spawned) == 1)
        check("dry-run freezes no run manifest",
              not (Path(world.config["outputs"]["intermediate_dir"]) / world.run_id
                   / mf.FRAGMENTS_DIR_NAME).exists())
        check("dry-run leaves the frozen contract untouched",
              prc.load_frozen(world.contract_path)["contract_sha256"] == world.contract_sha)


def test_continue_on_error_cannot_hide_infrastructure_failure():
    print("== --continue-on-error never hides a PRE_RUN_INFRASTRUCTURE_FAILURE ==")
    from thesis.generation import generate

    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp), provider="anthropic")
        original = generate.run_command
        # the child's REAL exit code for a pre-run infrastructure failure -
        # measured by the child-process tests above
        generate.run_command = lambda command, dry_run: \
            generate.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
        argv = sys.argv
        sys.argv = ["generate.py", "--config", str(world.config_path),
                    "--profile", "fixture", "--continue-on-error"]
        try:
            generate.main()
            stopped = False
        except generate.PreRunInfrastructureStop:
            stopped = True
        except SystemExit:
            stopped = False
        finally:
            sys.argv = argv
            generate.run_command = original
        check("the orchestrator STOPS instead of skipping the model", stopped)
        check("the stop is classified as a pre-run infrastructure failure",
              generate.PreRunInfrastructureStop.failure_class
              == "PRE_RUN_INFRASTRUCTURE_FAILURE")

        # the contrast case: an ORDINARY provider/model failure (exit 1) is
        # still skippable, so the stop above is specific to the infrastructure
        # exit code and not a blanket refusal
        generate.run_command = lambda command, dry_run: 1
        sys.argv = ["generate.py", "--config", str(world.config_path),
                    "--profile", "fixture", "--continue-on-error"]
        outcome = "no-exit"
        try:
            generate.main()
        except generate.PreRunInfrastructureStop:
            outcome = "stopped"
        except SystemExit as exit_:
            outcome = "reported-failures(%s)" % exit_.code
        finally:
            sys.argv = argv
            generate.run_command = original
        check("a provider/model failure is still skippable by --continue-on-error",
              outcome.startswith("reported-failures"))
        check("the two exit codes are distinct and shared with the runner",
              generate.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and generate.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE not in (0, 1))


def test_restart_preserves_authorization():
    print("== --restart continues the SAME authorized run ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        authorization = world.authorize()
        evidence_before = mf.fragment_path(
            Path(world.config["outputs"]["intermediate_dir"]), world.run_id,
            "runtime", "evidence").read_text(encoding="utf-8")
        spawn(world, "direct")
        result = spawn(world, "direct", extra=["--restart"])
        check("a --restart re-run rehydrates the same authorization",
              marker(result["out"], "AUTH_SHA") == authorization["authorization_sha256"])
        check("--restart deletes no authorization",
              (world.stored_authorization() or {}).get("authorization_sha256")
              == authorization["authorization_sha256"])
        check("--restart deletes no T0 runtime evidence",
              mf.fragment_path(Path(world.config["outputs"]["intermediate_dir"]),
                               world.run_id, "runtime", "evidence")
              .read_text(encoding="utf-8") == evidence_before)
        check("--restart leaves the frozen contract unchanged",
              prc.load_frozen(world.contract_path)["contract_sha256"] == world.contract_sha)


def test_contract_discovery_is_deterministic():
    print("== frozen contract discovery ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        discovery = ra.discover_frozen_contract(world.config, world.run_id)
        check("an unauthorized run finds the canonical run location",
              discovery["source"] == "canonical_run_location"
              and Path(discovery["path"]) == world.contract_path)
        explicit = ra.discover_frozen_contract(world.config, world.run_id,
                                               world.contract_path)
        check("an explicit contract path wins", explicit["source"] == "explicit_contract_path")
        world.authorize()
        world.contract_path.unlink()
        bound = ra.discover_frozen_contract(world.config, world.run_id)
        check("an authorized run falls back to the contract bound in its provenance",
              bound["source"] == "bound_run_provenance" and bound["contract"] is not None)
        check("the discovery order is declared",
              ra.CONTRACT_DISCOVERY_ORDER == ("explicit_contract_path",
                                              "canonical_run_location",
                                              "bound_run_provenance"))
    with tempfile.TemporaryDirectory() as tmp:
        world = ProviderWorld(Path(tmp))
        world.contract_path.unlink()
        result = spawn(world, "direct")
        check("no contract anywhere -> the run is classified UNCONTRACTED, never "
              "silently authorized",
              ra.MODE_UNCONTRACTED in result["out"]
              and "no frozen run contract" in result["out"])
        check("an UNCONTRACTED run installs no authorization",
              world.stored_authorization() is None)
        check("an UNCONTRACTED provider request is still REFUSED by the chokepoint",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and "MOCK_PROVIDER_REACHED" not in result["out"])
        check("legacy provenance without an authorization is CLASSIFIED, not migrated",
              ra.LEGACY_UNAUTHORIZED_BATCH_PROVENANCE
              == "LEGACY_UNAUTHORIZED_BATCH_PROVENANCE")

    with tempfile.TemporaryDirectory() as tmp:
        # a CONTRACTED run whose batch job was submitted outside the policy
        world = ProviderWorld(Path(tmp), api_mode="batch", provider="anthropic")
        result = spawn(world, "batch_poll", extra=["--poll"])
        check("a pure poll of a CONTRACTED but unauthorized run is fail-closed",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and ra.LEGACY_UNAUTHORIZED_BATCH_PROVENANCE in result["out"])
        check("legacy batch provenance is CLASSIFIED, never migrated",
              "never creates an authorization" in result["out"])
        check("the refused poll created no authorization",
              world.stored_authorization() is None)
        check("the refused poll reached no provider mock",
              "MOCK_POLL_REACHED" not in result["out"])

    with tempfile.TemporaryDirectory() as tmp:
        # batch bookkeeping from an EARLIER submission, but no authorization:
        # a plain (non-poll) re-run must not retro-authorize that job
        world = ProviderWorld(Path(tmp), api_mode="batch", provider="anthropic")
        world.out_dir().mkdir(parents=True, exist_ok=True)
        (world.out_dir() / "generation_batch.json").write_text(
            json.dumps({"batch_id": "legacy-job", "sample_ids": []}), encoding="utf-8")
        result = spawn(world, "batch_submit")
        check("an unauthorized run with EARLIER batch bookkeeping is never "
              "retro-authorized by a plain re-run",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and ra.LEGACY_UNAUTHORIZED_BATCH_PROVENANCE in result["out"])
        check("the refused re-run created no authorization and no provider job",
              world.stored_authorization() is None
              and "MOCK_SUBMIT_REACHED" not in result["out"])

    with tempfile.TemporaryDirectory() as tmp:
        # direct mode + --poll is a documented no-op: it must not probe the
        # runtime and must not persist an authorization
        world = ProviderWorld(Path(tmp))
        result = spawn(world, "direct", extra=["--poll"])
        check("direct-mode --poll stays a no-op: no authorization",
              world.stored_authorization() is None and result["rc"] == 0)
        check("direct-mode --poll stays a no-op: no runtime probe",
              marker(result["out"], "PROBES") in (None, "0"))

    with tempfile.TemporaryDirectory() as tmp:
        # a refused run must not have destroyed the measurement data first
        world = ProviderWorld(Path(tmp))
        world.authorize()
        spawn(world, "direct")
        generations = world.out_dir() / "generations.jsonl"
        before = generations.read_bytes()
        world.drift_contract()
        result = spawn(world, "direct", extra=["--restart"])
        check("a REFUSED --restart run does not delete the existing generations",
              result["rc"] == ra.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE
              and generations.is_file() and generations.read_bytes() == before)


def test_no_real_provider_calls():
    print("== no real provider call is reachable from this suite ==")
    from thesis.evaluation import provider_call_sites

    inventory = provider_call_sites.build_inventory()
    check("UNGUARDED_PROVIDER_CALL_SITES = []",
          inventory["UNGUARDED_PROVIDER_CALL_SITES"] == [])
    check("the chokepoints are unchanged",
          inventory["chokepoints"]["direct"].endswith("common.py::call_with_retries")
          and inventory["chokepoints"]["batch_submit"].endswith("batch_api.py::submit_batch"))
    check("the cross-process bootstrap introduced no new provider call site",
          inventory["counts"]["unguarded"] == 0)


def main() -> int:
    test_defect_is_real()
    test_first_start_child()
    test_rehydration_child()
    test_tampered_and_drifted_children()
    test_batch_processes()
    test_cross_process_resubmission()
    test_concurrent_children()
    test_registration_lock_under_contention()
    test_repair_process()
    test_dry_run_authorizes_nothing()
    test_continue_on_error_cannot_hide_infrastructure_failure()
    test_restart_preserves_authorization()
    test_contract_discovery_is_deterministic()
    test_no_real_provider_calls()

    print()
    if FAILURES:
        print("FAILURES (%d):" % len(FAILURES))
        for failure in FAILURES:
            print("  -", failure)
        return 1
    print("All cross-process authorization tests passed.")
    return 0


if __name__ == "__main__":
    if "--worker" in sys.argv:
        sys.exit(worker_main(sys.argv[1:]))
    sys.exit(main())
