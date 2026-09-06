"""Provider chokepoint enforcement + T0 authorization tests.

Proves the safety invariant of the pre-run enforcement wave:

    NO cost-causing provider request can technically be executed without a
    valid run authorization - not even from a caller that never invokes the
    runner-level T0 guard.

Every provider interaction here is a MOCK: the tests replace the private
provider helpers BELOW the chokepoints (batch_api._anthropic_submit / _poll)
or hand a mock `fn` to call_with_retries, so the real dispatchers - and
therefore the real guards - execute. No real OpenAI/Anthropic/Gemini/
DashScope request is made (API calls: 0).

Run:  python thesis/evaluation/test_provider_chokepoint.py
      python thesis/evaluation/test_provider_chokepoint.py --worker <mode> ...
"""
from __future__ import annotations

import argparse
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

from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import manifest_fragments as mf  # noqa: E402
from thesis.evaluation import provider_call_sites  # noqa: E402
from thesis.evaluation import run_authorization as ra  # noqa: E402
from thesis.evaluation.test_post_run_verification import (  # noqa: E402
    World, fake_environments, fake_prober)
from thesis.generation import batch_api, common  # noqa: E402

FAILURES = []


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


class MockProviderReached(AssertionError):
    """Raised by the mock provider so 'did we get there' is unambiguous."""


def mock_direct_call():
    raise MockProviderReached("MOCK PROVIDER REACHED (direct)")


def drifted_prober(config):
    """The same runtime with ONE changed identity - an image rebuild."""
    environments = fake_environments()
    environments["main"]["image_id"] = "sha256:" + "d" * 64
    return environments


# ---------------------------------------------------------------------------
# worker modes (separate processes for the concurrency fixtures)
# ---------------------------------------------------------------------------

def worker_authorize(config_path: str, contract_path: str, run_id: str,
                     mode: str) -> None:
    from thesis.config.load_config import load_config

    config = load_config(Path(config_path))
    prober = drifted_prober if mode == "drift" else fake_prober
    try:
        authorization = ra.authorize_start(config, config_path, "fixture", run_id,
                                           contract_path, prober=prober,
                                           allow_draft_contract=True)
        print("AUTHORIZED %s" % authorization["authorization_sha256"])
        # a guarded provider call must now be reachable
        try:
            common.call_with_retries(fn=mock_direct_call, retry_attempts=0,
                                     sleep_seconds=0, label="worker")
        except MockProviderReached:
            print("MOCK_REACHED")
    except ra.PreRunInfrastructureFailure as failure:
        print("REFUSED %s: %s" % (type(failure).__name__, failure))
        # and no provider call may be possible
        try:
            common.call_with_retries(fn=mock_direct_call, retry_attempts=0,
                                     sleep_seconds=0, label="worker")
            print("MOCK_REACHED_AFTER_REFUSAL")
        except ra.ProviderCallRefused:
            print("PROVIDER_REFUSED_AFTER_REFUSAL")
        except MockProviderReached:
            print("MOCK_REACHED_AFTER_REFUSAL")


def spawn(args):
    return subprocess.Popen([sys.executable, __file__, "--worker"] + [str(a) for a in args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            cwd=str(REPO_ROOT))


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_unguarded_callers():
    print("== a caller that never invokes the runner-level T0 guard ==")
    ra.clear_context()
    reached = {"direct": False, "batch": False}
    try:
        common.call_with_retries(fn=mock_direct_call, retry_attempts=0, sleep_seconds=0,
                                 label="unguarded")
    except ra.ProviderCallRefused as refusal:
        check("A: unguarded DIRECT caller -> REFUSED BEFORE MOCK PROVIDER",
              "no run authorization" in str(refusal))
    except MockProviderReached:
        reached["direct"] = True
    check("A2: the mock provider was never reached (direct)", not reached["direct"])

    original = batch_api._anthropic_submit
    batch_api._anthropic_submit = lambda *a, **k: reached.__setitem__("batch", True)
    try:
        batch_api.submit_batch(provider="anthropic", model_config={},
                               generation_defaults={}, system_prompt="",
                               requests=[("s", "t")])
        check("B: unguarded BATCH caller -> REFUSED BEFORE MOCK PROVIDER", False)
    except ra.ProviderCallRefused as refusal:
        check("B: unguarded BATCH caller -> REFUSED BEFORE MOCK PROVIDER",
              "no run authorization" in str(refusal))
    finally:
        batch_api._anthropic_submit = original
    check("B2: the mock submit was never reached", not reached["batch"])
    check("C: the refusal is a PRE_RUN_INFRASTRUCTURE_FAILURE, not a model failure",
          issubclass(ra.ProviderCallRefused, ra.PreRunInfrastructureFailure)
          and ra.PreRunInfrastructureFailure.failure_class == "PRE_RUN_INFRASTRUCTURE_FAILURE"
          and not issubclass(ra.ProviderCallRefused, common.ModelRefusal))


def test_authorized_callers(world: World):
    print("== an authorized run reaches the mock provider ==")
    ra.clear_context()
    authorization = ra.authorize_start(world.config, world.config_path, "fixture",
                                       world.run_id, world.contract_path,
                                       prober=fake_prober, allow_draft_contract=True)
    check("authorization is START_ALLOWED", authorization["decision"] == ra.DECISION_ALLOWED)
    try:
        common.call_with_retries(fn=mock_direct_call, retry_attempts=0, sleep_seconds=0,
                                 label="authorized")
        check("D: authorized DIRECT caller -> MOCK PROVIDER REACHED", False)
    except MockProviderReached:
        check("D: authorized DIRECT caller -> MOCK PROVIDER REACHED", True)

    submitted = {}
    original = batch_api._anthropic_submit
    batch_api._anthropic_submit = lambda *a, **k: submitted.setdefault("info", {"batch_id": "b-1"})
    try:
        info = batch_api.submit_batch(provider="anthropic", model_config={},
                                      generation_defaults={}, system_prompt="",
                                      requests=[("s", "t")])
        check("E: authorized BATCH caller -> MOCK SUBMIT REACHED",
              info == {"batch_id": "b-1"} and "info" in submitted)
    finally:
        batch_api._anthropic_submit = original

    polled = {}
    original_poll = batch_api._anthropic_poll
    batch_api._anthropic_poll = lambda *a, **k: polled.setdefault(
        "status", batch_api.BatchStatus(state="running", detail="in_progress"))
    try:
        batch_api.poll_batch(provider="anthropic", model_config={},
                             batch_info={"batch_id": "b-1"})
        check("F: a pure poll of an authorized job works without a new authorization",
              "status" in polled)
    finally:
        batch_api._anthropic_poll = original_poll
    return authorization


def test_authorization_properties(world: World, authorization):
    print("== authorization schema, fingerprint and ordering ==")
    check("schema and policy are versioned",
          authorization["schema_version"] == "run_start_authorization.v1"
          and authorization["authorization_policy_version"] == "provider_authorization_policy.v1")
    check("the methodical fingerprint is deterministic",
          ra.authorization_fingerprint(authorization) == authorization["authorization_sha256"])
    volatile = dict(authorization)
    volatile["authorized_at_utc"] = "2099-01-01T00:00:00.000000Z"
    volatile["pid"] = 999999
    volatile["hostname"] = "another-host"
    volatile["thread_id"] = 1
    volatile["probe_duration_seconds"] = 999.0
    check("volatile fields are EXCLUDED from the fingerprint",
          ra.authorization_fingerprint(volatile) == authorization["authorization_sha256"]
          and ra.AUTHORIZATION_VOLATILE_FIELDS_EXCLUDED_FROM_FINGERPRINT is True)
    methodical = dict(authorization)
    methodical["frozen_contract_sha256"] = "0" * 64
    check("a methodical field change DOES change the fingerprint",
          ra.authorization_fingerprint(methodical) != authorization["authorization_sha256"])
    check("volatile fields are still recorded in the content",
          set(ra.volatile_fields_present(authorization)) >= {"authorized_at_utc", "pid",
                                                             "hostname", "thread_id"})

    intermediate = Path(world.config["outputs"]["intermediate_dir"])
    fragments = dict(mf.load_fragments(intermediate, world.run_id))
    order = [(name, fragment["registered_at_utc"]) for name, fragment in fragments.items()
             if name in ("contract.json", "runtime.evidence.json", "authorization.start.json")]
    order.sort(key=lambda item: item[1])
    names = [name for name, _ in order]
    check("the authorization is committed AFTER the contract binding",
          names.index("contract.json") < names.index("authorization.start.json"))
    check("the authorization is committed AFTER the runtime binding",
          names.index("runtime.evidence.json") < names.index("authorization.start.json"))
    stored = ra.load_authorization(world.config, world.run_id)
    check("the authorization is read back from the run provenance before any call",
          stored is not None
          and ra.authorization_fingerprint(stored) == authorization["authorization_sha256"])

    evidence = (mf.merge_fragments(intermediate, world.run_id).get("runtime_evidence") or {})
    check("T0 runtime evidence is versioned and complete",
          evidence.get("evidence_version") == "t0_runtime_evidence.v2"
          and set(evidence.get("domains") or {}) == {"main", "parcoach", "llov"}
          and evidence.get("t0_requires_docker_and_all_three_images") is True)
    check("T0 evidence carries the per-domain identities the contract requires",
          (evidence["domains"]["main"]["tool_identities"] or {}).get("compiler")
          and (evidence["domains"]["main"]["tool_identities"] or {}).get("mpi")
          and (evidence["domains"]["parcoach"]["evidence"] or {}).get("executable_sha256")
          and (evidence["domains"]["llov"]["evidence"] or {}).get("plugin_sha256"))


def test_runtime_gates(world_factory):
    print("== T0 refuses every runtime drift and every unresolvable probe ==")
    cases = [
        ("stale main image", lambda e: _mutate(e, "main", "image_id", "sha256:" + "9" * 64)),
        ("stale compiler", lambda e: _mutate_identity(e, "main", "compiler", "g++ 14.0.0")),
        ("stale MPI runtime", lambda e: _mutate_identity(e, "main", "mpi", "mpirun 5.0.0")),
        ("stale PARCOACH executable",
         lambda e: _mutate_evidence(e, "parcoach", "executable_sha256", "f" * 64)),
        ("stale LLOV image", lambda e: _mutate(e, "llov", "image_id", "sha256:" + "a" * 64)),
        ("stale LLOV plugin",
         lambda e: _mutate_evidence(e, "llov", "plugin_sha256", "b" * 64)),
    ]
    for label, mutate in cases:
        with tempfile.TemporaryDirectory() as tmp:
            world = world_factory(tmp)
            ra.clear_context()
            _reset_authorization(world)

            def prober(config, mutate=mutate):
                return mutate(fake_environments())

            try:
                ra.authorize_start(world.config, world.config_path, "fixture", world.run_id,
                                   world.contract_path, prober=prober,
                                   allow_draft_contract=True)
                check("%s -> START_REFUSED" % label, False)
            except ra.StartRefused as refusal:
                check("%s -> START_REFUSED" % label, "runtime drift" in str(refusal)
                      or "pins runtime" in str(refusal))
            check("%s -> no authorization was written" % label,
                  ra.load_authorization(world.config, world.run_id) is None)

    with tempfile.TemporaryDirectory() as tmp:
        world = world_factory(tmp)
        ra.clear_context()
        _reset_authorization(world)

        def broken(config):
            environments = fake_environments()
            environments["parcoach"]["probe_error"] = "docker unavailable"
            environments["parcoach"]["image_id"] = None
            environments["parcoach"]["repo_digests"] = []
            environments["parcoach"]["rootfs_layers_sha256"] = None
            return environments

        try:
            ra.authorize_start(world.config, world.config_path, "fixture", world.run_id,
                               world.contract_path, prober=broken, allow_draft_contract=True)
            check("a runtime probe failure -> PRE_RUN_RUNTIME_UNRESOLVED", False)
        except ra.RuntimeUnresolved as refusal:
            check("a runtime probe failure -> PRE_RUN_RUNTIME_UNRESOLVED",
                  "PRE_RUN_RUNTIME_UNRESOLVED" in str(refusal))
        check("T0 requires docker and all three images (documented)",
              ra.T0_REQUIRES_DOCKER_AND_ALL_THREE_IMAGES is True
              and tuple(ra.REQUIRED_RUNTIME_DOMAINS) == ("main", "parcoach", "llov"))


def _reset_authorization(world: World):
    """Back to the state right before the FIRST cost-causing request: the
    contract exists, but nothing is authorized and no T0 evidence is bound."""
    intermediate = Path(world.config["outputs"]["intermediate_dir"])
    for kind, owner in (("authorization", "start"), ("runtime", "evidence")):
        path = mf.fragment_path(intermediate, world.run_id, kind, owner)
        if path.is_file():
            path.unlink()
    mf.write_snapshot(intermediate, world.run_id)


def _mutate(environments, domain, field, value):
    environments[domain][field] = value
    return environments


def _mutate_identity(environments, domain, tool, value):
    environments[domain]["tool_identities"][tool] = value
    return environments


def _mutate_evidence(environments, domain, key, value):
    environments[domain]["evidence"][key] = value
    return environments


def test_concurrent_first_start(world: World, workers: int = 8):
    print("== %d concurrent first starts ==" % workers)
    procs = [spawn(["authorize", world.config_path, world.contract_path, world.run_id, "ok"])
             for _ in range(workers)]
    outputs = [p.communicate()[0] for p in procs]
    authorized = [line.split()[1] for out in outputs for line in out.splitlines()
                  if line.startswith("AUTHORIZED ")]
    refused = [out for out in outputs if "REFUSED" in out]
    reached = sum(1 for out in outputs if "MOCK_REACHED" in out)
    intermediate = Path(world.config["outputs"]["intermediate_dir"])
    fragments = [name for name, _ in mf.load_fragments(intermediate, world.run_id)
                 if name.startswith("authorization.")]
    print("  %d authorized, %d refused, %d reached the mock, %d authorization fragment(s)"
          % (len(authorized), len(refused), reached, len(fragments)))
    check("every concurrent starter succeeded", len(authorized) == workers and not refused)
    check("exactly ONE canonical authorization exists", len(fragments) == 1)
    check("all starters see the SAME methodical authorization fingerprint",
          len(set(authorized)) == 1)
    check("no timestamp/pid drift in the fingerprint",
          set(authorized) == {ra.load_authorization(world.config, world.run_id)[
              "authorization_sha256"]})
    check("every authorized starter reached the mock provider", reached == workers)
    for out in outputs:
        if "MOCK_REACHED_AFTER_REFUSAL" in out:
            check("no starter reached the provider after a refusal", False)


def test_concurrent_runtime_drift(world: World):
    print("== a starter whose runtime drifted between the probes ==")
    before = ra.load_authorization(world.config, world.run_id)
    proc = spawn(["authorize", world.config_path, world.contract_path, world.run_id, "drift"])
    out = proc.communicate()[0]
    after = ra.load_authorization(world.config, world.run_id)
    intermediate = Path(world.config["outputs"]["intermediate_dir"])
    fragments = [name for name, _ in mf.load_fragments(intermediate, world.run_id)
                 if name.startswith("authorization.")]
    check("the drifted starter is REFUSED", "REFUSED" in out)
    check("the drifted starter reached no provider mock", "MOCK_REACHED" not in out)
    check("the existing authorization is unchanged",
          before["authorization_sha256"] == after["authorization_sha256"])
    check("no second, contradicting authorization was written", len(fragments) == 1)


def test_new_submission_revalidation(world: World):
    print("== every NEW submission revalidates contract and runtime ==")
    ra.clear_context()
    ra.authorize_start(world.config, world.config_path, "fixture", world.run_id,
                       world.contract_path, prober=fake_prober, allow_draft_contract=True)
    submitted = []
    original = batch_api._anthropic_submit
    batch_api._anthropic_submit = lambda *a, **k: submitted.append("job") or {"batch_id": "b"}
    try:
        batch_api.submit_batch(provider="anthropic", model_config={}, generation_defaults={},
                               system_prompt="", requests=[("s", "t")])
        check("A: no drift -> the mock submit is reached", submitted == ["job"])

        # runtime drift before the next submission
        context = ra.current_context()
        ra._install_context(dict(context, prober=drifted_prober))
        try:
            batch_api.submit_batch(provider="anthropic", model_config={},
                                   generation_defaults={}, system_prompt="",
                                   requests=[("s", "t")])
            check("C: runtime drift -> NEW_SUBMISSION_REFUSED", False)
        except ra.ProviderCallRefused as refusal:
            check("C: runtime drift -> NEW_SUBMISSION_REFUSED",
                  "NEW_SUBMISSION_REFUSED" in str(refusal))
        check("C2: no new provider job was created", submitted == ["job"])
        ra._install_context(context)

        # contract drift before the next submission
        text = Path(world.config_path).read_text(encoding="utf-8")
        Path(world.config_path).write_text(
            text.replace("run_timeout_seconds: 120", "run_timeout_seconds: 90"),
            encoding="utf-8")
        try:
            batch_api.submit_batch(provider="anthropic", model_config={},
                                   generation_defaults={}, system_prompt="",
                                   requests=[("s", "t")])
            check("B: contract drift -> NEW_SUBMISSION_REFUSED", False)
        except ra.ProviderCallRefused as refusal:
            check("B: contract drift -> NEW_SUBMISSION_REFUSED",
                  "NEW_SUBMISSION_REFUSED" in str(refusal))
        check("B2: no new provider job was created", submitted == ["job"])
        Path(world.config_path).write_text(text, encoding="utf-8")
    finally:
        batch_api._anthropic_submit = original


def test_real_batch_response_missing_resubmission():
    print("== the REAL BatchResponseMissing resubmission path ==")
    from thesis.generation import test_generation as tg

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), run_id="pilot_002_batch")
        ra.clear_context()
        ra.authorize_start(world.config, world.config_path, "fixture", world.run_id,
                           world.contract_path, prober=fake_prober, allow_draft_contract=True)

        config_path, out_dir, adapter = _batch_world(world)
        submits = []
        polls = {"n": 0}

        def fake_submit(model_config, generation_defaults, system_prompt, requests, **kw):
            submits.append([sample_id for sample_id, _text in requests])
            return {"batch_id": "job-%d" % len(submits)}

        def fake_poll(model_config, batch_info):
            polls["n"] += 1
            sample_ids = batch_info["sample_ids"]
            # ONE request comes back without a response: the real
            # BatchResponseMissing bookkeeping path
            responses = {sample_ids[0]: batch_api.BatchItemResponse(
                raw_text="```cpp\nvoid relu(std::vector<double> &x) {}\n```",
                finish_reason="completed", truncated=False, response_id="r-1",
                usage={"input_tokens": 5, "output_tokens": 7})}
            return batch_api.BatchStatus(state="completed", detail="completed",
                                         responses=responses)

        original = (batch_api._anthropic_submit, batch_api._anthropic_poll)
        batch_api._anthropic_submit, batch_api._anthropic_poll = fake_submit, fake_poll
        try:
            _run_generation(config_path, adapter)                    # submit
            check("the first submission went through the guarded chokepoint",
                  len(submits) == 1 and len(submits[0]) == 2)
            _run_generation(config_path, adapter, ["--poll"])        # poll: 1 missing
            check("the poll consumed the bookkeeping (job file renamed to .done.json)",
                  (out_dir / "generation_batch.done.json").exists()
                  and not (out_dir / "generation_batch.json").exists())

            # A: no drift -> the real resubmission is allowed
            _run_generation(config_path, adapter)
            check("A: the real resubmission reached the mock submit",
                  len(submits) == 2 and len(submits[1]) == 1)

            # B: contract drift -> refused, no new provider job
            (out_dir / "generation_batch.json").unlink(missing_ok=True)
            text = Path(world.config_path).read_text(encoding="utf-8")
            Path(world.config_path).write_text(
                text.replace("run_timeout_seconds: 120", "run_timeout_seconds: 45"),
                encoding="utf-8")
            try:
                _run_generation(config_path, adapter)
                check("B: contract drift -> resubmission REFUSED", False)
            except ra.ProviderCallRefused:
                check("B: contract drift -> resubmission REFUSED", True)
            check("B2: no new provider job", len(submits) == 2)
            Path(world.config_path).write_text(text, encoding="utf-8")

            # C: runtime drift -> refused, no new provider job
            context = ra.current_context()
            ra._install_context(dict(context, prober=drifted_prober))
            try:
                _run_generation(config_path, adapter)
                check("C: runtime drift -> resubmission REFUSED", False)
            except ra.ProviderCallRefused:
                check("C: runtime drift -> resubmission REFUSED", True)
            check("C2: no new provider job", len(submits) == 2)
            ra._install_context(context)
        finally:
            batch_api._anthropic_submit, batch_api._anthropic_poll = original


class AnthropicFakeAdapter(object):
    """The generation adapter seam: batch mode never calls generate(), and
    the provider decides which private submit helper the REAL dispatcher
    reaches - which is exactly the code path under test."""

    provider = "anthropic"
    default_api_key_env = "FAKE_GEN_KEY"

    def create_client(self, model_config, api_key, timeout_seconds=None):
        return object()

    def generation_parameters(self, model_config, generation_defaults):
        return {"max_output_tokens": 512}

    def generate(self, *args, **kwargs):
        raise AssertionError("batch mode must not call generate()")


def _batch_world(world: World):
    """A generation world (batch mode, anthropic) on top of the fixture run."""
    import yaml

    from thesis.generation import test_generation as tg

    gen_dir = Path(world.root) / "gen"
    gen_dir.mkdir(parents=True, exist_ok=True)
    config_path, _raw = tg.write_world(gen_dir, api_mode="batch")
    # the generation config must write into the same run/output tree as the
    # authorized fixture run, so the guard sees the same run provenance
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    config["outputs"] = {k: v for k, v in world.config["outputs"].items()}
    config["profiles"]["unit"]["run_id"] = world.run_id
    for model in config.get("models", []):
        model["provider"] = "anthropic"
    Path(config_path).write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    out_dir = Path(config["outputs"]["raw_dir"]) / world.run_id / "fake_model"
    return config_path, out_dir, AnthropicFakeAdapter()


def _run_generation(config_path, adapter, extra=()):
    old = sys.argv
    os.environ["FAKE_GEN_KEY"] = "x"
    sys.argv = ["gen", "--config", str(config_path), "--profile", "unit",
                "--model-id", "fake_model"] + list(extra)
    try:
        common.run_generation(adapter)
    finally:
        sys.argv = old


def test_infrastructure_failure_is_not_a_model_failure():
    print("== an authorization failure never becomes a model/generation record ==")
    import tempfile as _tempfile

    from thesis.generation import test_generation as tg

    class ChokepointAdapter(tg.FakeAdapter):
        """Routes through the productive direct chokepoint exactly like the
        four real adapters (`common.call_with_retries(fn=lambda: <sdk>)`)."""

        def generate(self, client, model_config, generation_defaults, system_prompt,
                     messages, retry_attempts, sleep_seconds):
            common.call_with_retries(fn=mock_direct_call, retry_attempts=0,
                                     sleep_seconds=0, label="fake adapter")
            raise AssertionError("unreachable: the mock provider raises")

    with _tempfile.TemporaryDirectory() as tmp:
        config_path, raw = tg.write_world(Path(tmp), api_mode="direct")
        adapter = ChokepointAdapter()
        ra.clear_context()
        try:
            _run_generation(config_path, adapter)
            check("the direct runner ABORTS instead of writing a failure record", False)
        except ra.PreRunInfrastructureFailure as failure:
            check("the direct runner ABORTS instead of writing a failure record",
                  failure.failure_class == "PRE_RUN_INFRASTRUCTURE_FAILURE")
        records = list((Path(raw) / "unit_run" / "fake_model").glob("generations.jsonl"))
        written = []
        if records:
            written = [json.loads(line) for line in
                       records[0].read_text(encoding="utf-8").splitlines() if line.strip()]
        check("no generation record that looks like a model failure was written",
              not written)


def test_call_site_inventory():
    print("== AST audit of every provider call site ==")
    inventory = provider_call_sites.build_inventory()
    counts = inventory["counts"]
    print("  %d provider call sites, %d cost-causing, %d guarded, %d unguarded"
          % (counts["provider_call_sites"], counts["cost_causing"], counts["guarded"],
             counts["unguarded"]))
    check("UNGUARDED_PROVIDER_CALL_SITES = []",
          inventory["UNGUARDED_PROVIDER_CALL_SITES"] == [])
    check("every cost-causing site resolves to a chokepoint",
          all(site["chokepoint"] for site in inventory["GUARDED_PROVIDER_CALL_SITES"]))
    check("both chokepoints are the ones this wave guards",
          inventory["chokepoints"]["direct"].endswith("common.py::call_with_retries")
          and inventory["chokepoints"]["batch_submit"].endswith("batch_api.py::submit_batch"))
    check("the batch submit sites of all three providers are covered",
          len(inventory["PROVIDER_SUBMIT_SITES"]) >= 3)
    for site in inventory["UNGUARDED_PROVIDER_CALL_SITES"]:
        print("   UNGUARDED:", site["file"], site["line"], site["call"])


def test_sdk_client_construction_has_no_network():
    print("== SDK client construction performs no network I/O (measured) ==")
    import socket

    attempts = []
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo
    socket.socket.connect = lambda self, addr, *a, **k: attempts.append(("connect", addr))
    socket.getaddrinfo = lambda *a, **k: attempts.append(("getaddrinfo", a[:2])) or []
    try:
        try:
            from anthropic import Anthropic

            Anthropic(api_key="sk-test-not-real")
        except ImportError:
            pass
        try:
            from openai import OpenAI

            OpenAI(api_key="sk-test-not-real")
            OpenAI(api_key="sk-test-not-real", base_url="https://example.invalid/v1")
        except ImportError:
            pass
        try:
            from google import genai

            genai.Client(api_key="test-not-real")
        except ImportError:
            pass
    finally:
        socket.socket.connect = real_connect
        socket.getaddrinfo = real_getaddrinfo
    check("client construction opens no connection (the guard may sit at the request)",
          attempts == [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("rest", nargs="*")
    args = parser.parse_args()
    if args.worker:
        mode = args.rest[0]
        if mode == "authorize":
            worker_authorize(args.rest[1], args.rest[2], args.rest[3], args.rest[4])
        return

    test_unguarded_callers()
    test_infrastructure_failure_is_not_a_model_failure()
    test_call_site_inventory()
    test_sdk_client_construction_has_no_network()

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        authorization = test_authorized_callers(world)
        test_authorization_properties(world, authorization)
        test_new_submission_revalidation(world)

    test_runtime_gates(lambda tmp: World(Path(tmp)))

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), run_id="pilot_002_parallel")
        # remove the authorization the fixture created, so the workers race
        # for the FIRST start
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        mf.fragment_path(intermediate, world.run_id, "authorization", "start").unlink()
        mf.write_snapshot(intermediate, world.run_id)
        test_concurrent_first_start(world)
        test_concurrent_runtime_drift(world)

    test_real_batch_response_missing_resubmission()

    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for item in FAILURES:
            print("  -", item)
        sys.exit(1)
    print("All provider chokepoint / authorization tests passed.")


if __name__ == "__main__":
    main()
