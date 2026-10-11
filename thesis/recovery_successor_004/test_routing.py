"""Synthetic end-to-end tests of the fresh successor run (full_ext_recovery_004).

No provider, no analysis tool, no authorization, no repository result file is
touched: every test builds its own world in a temporary directory.

The world: a synthetic full_ext_001 parent for the five 004 models and one
origin model, a synthetic recovery_001 that ran the origin model NATIVELY
(iteration 0 routed to the parent, stopped where the real recovery_001
stopped: static/combined waiting for external tools at iteration 1,
test_feedback done), and the two protected sibling successors 002/003. The
successor then runs all 15 loops FRESH through the real SuccessorRepairLoop
/ run.drive (schedule api_first.v2) with a mock provider, mock LLOV/PARCOACH
containers (native-shaped entries) and stubbed internal analyses; the result
is checked by the real per-loop verifier.

Run (main container, Python 3.12):
    python3 -B -m unittest thesis.recovery_successor_004.test_routing
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import framework  # noqa: E402
from thesis.evaluation import recovery_lineage as rl  # noqa: E402
from thesis.evaluation import run_static_analysis as rsa  # noqa: E402
from thesis.evaluation import successor_supplement as ss  # noqa: E402
from thesis.evaluation import successor_writer as sw  # noqa: E402
from thesis.evaluation import tools as tool_module  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused  # noqa: E402
from thesis.evaluation.tool_config import resolve_tool_settings  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.recovery_successor_004 import external as sx  # noqa: E402
from thesis.recovery_successor_004 import handoff as sh  # noqa: E402
from thesis.recovery_successor_004 import lineage as sl  # noqa: E402
from thesis.recovery_successor_004 import routing as sr  # noqa: E402
from thesis.recovery_successor_004 import run as rs  # noqa: E402
from thesis.recovery_successor_004 import verify as vs  # noqa: E402
from thesis.repair import orchestrator  # noqa: E402
from thesis.repair.test_orchestrator import FIXED_ANSWER, PROMPT_TEXT  # noqa: E402

KEY_ENV = "FAKE_SUCCESSOR_KEY"
ORIGIN_MODEL = "qwen3_coder_api"      # ran natively in the synthetic recovery_001
SIBLING_MODEL = "claude_fable_5"      # owns the synthetic 002/003 sibling trees
ALIBABA = ("deepseek_v4_pro", "qwen36_35b_a3b", "qwen37_max")
# (execution model, sample index, assembled at iteration 0)
SPECS = (("omp", 0, True), ("omp", 1, True), ("mpi", 0, True), ("serial", 0, True),
         ("omp", 2, False))
CALLS_PER_MODEL = {"static_feedback": 5, "test_feedback": 4, "combined_feedback": 5}


def sample_id(model, execution_model, index):
    return "%s__reduce__27_reduce_average__%s__sample_%d" % (model, execution_model, index)


def execution_model(sample):
    return sample.split("__")[-2]


def compiler_dirty(sample, iteration):
    model = execution_model(sample)
    if model == "serial":
        return False
    return iteration == 0 or model == "mpi"


def llov_dirty(sample, iteration):
    return iteration == 1 and sample.endswith("__omp__sample_0")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def quiet(*_args, **_kwargs):
    return None


def counts():
    return OrderedDict([("reused", Counter()), ("new", Counter()), ("terminal", OrderedDict())])


class SimulatedCrash(BaseException):
    """A BaseException like KeyboardInterrupt/SystemExit: nothing catches it."""


class FakeAdapter:
    """Mock provider: records every request; 'ok' answers FIXED_ANSWER."""

    provider = "openai_compatible"
    default_api_key_env = KEY_ENV

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
        # behaviours consumed per call in submission order (a loop submits its
        # requests sorted by sample id: mpi_sample_0 before omp_sample_0)
        self.sequence = []
        self.fail_models = set()
        self.fail_after = None  # (models, n): calls of these models fail after their first n

    def create_client(self, model_config, api_key, timeout_seconds=None):
        return object()

    def generation_parameters(self, model_config, generation_defaults):
        return {"fake": True}

    def generate(self, client, model_config, generation_defaults, system_prompt, messages,
                 retry_attempts, sleep_seconds):
        text = messages[0]["content"]
        with self.lock:
            self.calls.append((model_config["id"], sha256(text.encode("utf-8"))))
            behaviour = self.sequence.pop(0) if self.sequence else "ok"
            outage = False
            if self.fail_after is not None:
                models, allowed = self.fail_after
                if model_config["id"] in models:
                    outage = len([c for c in self.calls if c[0] in models]) > allowed
        if model_config["id"] in self.fail_models or outage:
            raise RuntimeError("simulated provider outage")
        if behaviour == "crash":
            raise SimulatedCrash("process killed while the request was in flight")
        if behaviour == "chokepoint":
            from thesis.evaluation.run_authorization import PreRunInfrastructureFailure
            raise PreRunInfrastructureFailure("authorization refused before send")
        if behaviour == "error":
            raise RuntimeError("simulated transport failure")
        return common.GenerationResult(raw_text=FIXED_ANSWER, finish_reason="stop", truncated=False,
                                       response_id="fake", usage={"prompt_tokens": 3,
                                                                  "completion_tokens": 2})


class FakeLLOV(tool_module.LLOVTool):
    def is_available(self):
        return True

    def run(self, sample, context):
        iteration = 2 if "__iter2" in sample.run_id else 1
        findings = []
        if llov_dirty(sample.sample_id, iteration):
            findings.append(framework.Finding("llov", "data-race", "error", "data race on 'sum'",
                                              "generated-code.hpp", 5, 1, True))
        return framework.ToolResult(tool="llov", ran=True, exit_code=0, duration_seconds=0.25,
                                    findings=findings, analysis_state=framework.STATE_COMPLETED)


class FakeParcoach(tool_module.ParcoachTool):
    def is_available(self):
        return True

    def run(self, sample, context):
        return framework.ToolResult(tool="parcoach", ran=True, exit_code=0, duration_seconds=0.5,
                                    findings=[], analysis_state=framework.STATE_COMPLETED)


class FakeAuthority:
    contract_sha256 = "c" * 64
    authorization_sha256 = "a" * 64

    def __init__(self):
        self.checks = 0
        self.refuse = False

    def check(self):
        self.checks += 1
        if self.refuse:
            raise RecoveryRefused("authority withdrawn")
        return {"authorization": {"authorization_sha256": self.authorization_sha256}}


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.waits = []
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.now

    def wait(self, seconds):
        with self.lock:
            self.waits.append(seconds)
            self.now += seconds


class World:
    """Synthetic parent (full_ext_001), origin (recovery_001) and siblings."""

    def __init__(self, tmp):
        from thesis.config.load_config import load_config

        self.root = Path(tmp).resolve()
        config = copy.deepcopy(load_config(REPO_ROOT / sl.CONFIG_REL))
        config["outputs"] = dict(config["outputs"],
                                 raw_dir=(self.root / "thesis/results/raw").as_posix(),
                                 intermediate_dir=(self.root / "thesis/results/intermediate").as_posix())
        config["generation_defaults"] = dict(config["generation_defaults"],
                                             sleep_seconds_between_requests=0.0, retry_attempts=0)
        for model in config["models"]:
            if model["id"] in sl.MODELS + (ORIGIN_MODEL,):
                model["api_key_env"] = KEY_ENV
        self.config = config
        self.static_settings = resolve_tool_settings(config, "static_analysis")
        self.dynamic_settings = {n: s for n, s in resolve_tool_settings(config, "dynamic_analysis").items()
                                 if s.enabled}
        self.models = {m["id"]: m for m in config["models"] if m["id"] in sl.MODELS + (ORIGIN_MODEL,)}
        self.context = framework.EvaluationContext(
            repo_root=REPO_ROOT, drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
            primary_compiler="g++", config=config)
        os.environ[KEY_ENV] = "fake-key"

    # -- records ----------------------------------------------------------

    def tool_entry(self, name, settings, sample, iteration):
        model = execution_model(sample)
        if not settings.applies_to(model):
            return rsa.not_applicable_entry(name, model)
        findings = []
        if name == "compiler" and compiler_dirty(sample, iteration):
            findings.append(framework.Finding("compiler", "error", "error",
                                              "use of undeclared identifier 'summ'",
                                              "generated-code.hpp", 6, 1, True))
        if name == "llov" and llov_dirty(sample, iteration):
            findings.append(framework.Finding("llov", "data-race", "error", "data race on 'sum'",
                                              "generated-code.hpp", 5, 1, True))
        return framework.ToolResult(tool=name, ran=True, exit_code=0, duration_seconds=0.1,
                                    findings=findings,
                                    analysis_state=framework.STATE_COMPLETED).to_dict()

    def static_record(self, run, model_id, sample, iteration, tools, source_sha):
        record = OrderedDict([
            ("schema_version", "static_analysis.v3"), ("run_id", run), ("model_id", model_id),
            ("sample_id", sample), ("execution_model", execution_model(sample)),
            ("tools", OrderedDict((n, self.tool_entry(n, self.static_settings[n], sample, iteration))
                                  for n in tools)),
            ("sample_source_sha256", source_sha)])
        record["has_blocking_findings"] = rsa.record_has_blocking(record)
        record["low_confidence_count"] = rsa.record_low_confidence_count(record)
        record["analysis_gaps"] = rsa.record_analysis_gaps(record)
        return record

    def correctness_record(self, run, model_id, sample, iteration):
        return OrderedDict([("run_id", run), ("model_id", model_id), ("sample_id", sample),
                            ("execution_model", execution_model(sample)),
                            ("verdict", "fail" if compiler_dirty(sample, iteration) else "pass"),
                            ("runs", [])])

    def dynamic_record(self, run, model_id, sample, iteration):
        return OrderedDict([("run_id", run), ("model_id", model_id), ("sample_id", sample),
                            ("execution_model", execution_model(sample)),
                            ("tools", OrderedDict((n, self.tool_entry(n, s, sample, iteration))
                                                  for n, s in self.dynamic_settings.items()))])

    @staticmethod
    def write_jsonl(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))

    def write_analyses(self, loop, iteration, stages, externals=()):
        """Internal analyses of one iteration (the stubbed in-container stages)."""
        run = loop.paths.iter_run_id(iteration)
        samples = loop.iteration_samples(iteration)
        if "static" in stages:
            tools = list(loop.internal_static_settings()) + list(externals)
            rows = [self.static_record(run, loop.model_id, s, iteration, tools,
                                       sha256(loop.paths.source_path(iteration, s).read_bytes()))
                    for s in samples]
            self.write_jsonl(loop.paths.stage_path(iteration, "static_analysis"), rows)
        if "correctness" in stages:
            self.write_jsonl(loop.paths.stage_path(iteration, "correctness_tests"),
                             [self.correctness_record(run, loop.model_id, s, iteration) for s in samples])
        if "dynamic" in stages:
            self.write_jsonl(loop.paths.stage_path(iteration, "dynamic_analysis"),
                             [self.dynamic_record(run, loop.model_id, s, iteration) for s in samples])

    # -- parent -----------------------------------------------------------

    def write_parent(self, model_id):
        model = self.models[model_id]
        raw = self.root / "thesis/results/raw" / sl.PARENT / model_id
        intermediate = self.root / "thesis/results/intermediate" / sl.PARENT / model_id
        generations, assembly, static, correctness, dynamic = [], [], [], [], []
        static_tools = [n for n, s in self.static_settings.items() if s.enabled]
        for em, index, assembled in SPECS:
            sample = sample_id(model_id, em, index)
            generations.append(OrderedDict([
                ("schema_version", "generation.v2"), ("run_id", sl.PARENT), ("sample_id", sample),
                ("model", {"id": model_id, "provider": model["provider"],
                           "model_name": model.get("model_name")}),
                ("prompt", {"problem_type": "reduce", "name": "27_reduce_average", "language": "cpp",
                            "parallelism_model": em, "prompt_field": "prompt",
                            "prompt_text": PROMPT_TEXT}),
                ("generation_parameters", {"sample_index": index}),
                ("output", {"raw_text": "    return 0.0;\n}"}),
                ("status", {"success": True, "truncated": False})]))
            entry = OrderedDict([("run_id", sl.PARENT), ("model_id", model_id), ("sample_id", sample),
                                 ("assembled", assembled)])
            if not assembled:
                entry["skip_reason"] = "no_code_found"
                assembly.append(entry)
                continue
            source = intermediate / "sources" / sample / "generated-code.hpp"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes((PROMPT_TEXT + "\n    return 0.0;\n}\n").encode("utf-8"))
            entry["source_path"] = source.as_posix()
            entry["drivers"] = {"benchmark_dir": "drivers/cpp/benchmarks/reduce/27_reduce_average",
                                "model_driver": "drivers/cpp/models/%s-driver.cc" % em}
            assembly.append(entry)
            static.append(self.static_record(sl.PARENT, model_id, sample, 0, static_tools,
                                             sha256(source.read_bytes())))
            correctness.append(self.correctness_record(sl.PARENT, model_id, sample, 0))
            dynamic.append(self.dynamic_record(sl.PARENT, model_id, sample, 0))
        self.write_jsonl(raw / "generations.jsonl", generations)
        self.write_jsonl(intermediate / "assembly.jsonl", assembly)
        self.write_jsonl(intermediate / orchestrator.stage_output_file(self.config, "static_analysis"), static)
        self.write_jsonl(intermediate / orchestrator.stage_output_file(self.config, "correctness_tests"),
                         correctness)
        self.write_jsonl(intermediate / orchestrator.stage_output_file(self.config, "dynamic_analysis"),
                         dynamic)

    def parent_lineage(self):
        artifacts = []
        for area in ("raw", "intermediate"):
            base = self.root / "thesis/results" / area / sl.PARENT
            for path in sorted(p for p in base.rglob("*") if p.is_file()):
                relative = path.relative_to(self.root).as_posix()
                data = path.read_bytes()
                artifacts.append(OrderedDict([
                    ("path", relative), ("raw_sha256", sha256(data)), ("size", len(data)),
                    ("stage", "source" if "/sources/" in relative else path.stem),
                    ("source_run", sl.PARENT), ("model_id", relative.split("/")[4])]))
        artifacts.sort(key=lambda row: row["path"])
        document = OrderedDict([
            ("schema_version", rl.SCHEMA), ("run_id", rl.RECOVERY), ("parent_run_id", rl.PARENT),
            ("pilot_run_id", rl.PILOT), ("stage_ownership", rl.OWNERSHIP), ("recovery_base_cells", 0),
            ("historical_repair_policy", "EXCLUDE_ALL_PARENT_REPAIR"),
            ("model_ids", list(sl.MODELS) + [ORIGIN_MODEL]), ("max_iterations", 2),
            ("artifacts", artifacts)])
        document["lineage_sha256"] = rl.fingerprint(document)
        target = self.root / sl.PREDECESSOR_DEFINITIONS_REL / "lineage.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document), encoding="utf-8")
        return rl.RecoveryLineage(self.root, document, document["lineage_sha256"])

    # -- origin recovery_001 (native loop) ----------------------------------

    def run_origin(self, variant, adapter):
        world = self

        class OriginPaths(orchestrator.LoopPaths):
            def iter_run_id(self, iteration):
                return sl.PARENT if iteration == 0 else super().iter_run_id(iteration)

        class OriginLoop(orchestrator.RepairLoop):
            def _run_analysis_stages(self, iteration, stages):
                assert iteration >= 1
                world.write_analyses(self, iteration, stages)

            def run_external_docker(self, pending, iteration):
                return [tool for tool, _count in pending]  # the LLOV gate refused

            def log(self, message):
                return None

        loop = OriginLoop(self.config, "synthetic.yaml", "recovery", {"run_id": sl.PREDECESSOR},
                          self.models[ORIGIN_MODEL], variant, "g++", lambda provider: adapter)
        loop.paths = OriginPaths(self.config, sl.PREDECESSOR, ORIGIN_MODEL, variant)
        for _ in range(60):
            outcome = loop.step()
            if outcome in (orchestrator.OUTCOME_DONE, orchestrator.OUTCOME_BLOCKED_EXTERNAL):
                return outcome
        raise AssertionError("synthetic origin loop did not settle")

    def write_sibling(self, run):
        for variant in ("static_feedback", "combined_feedback"):
            repair = self.root / "thesis/results/intermediate" / run / SIBLING_MODEL / "repair" / variant
            repair.mkdir(parents=True, exist_ok=True)
            (repair / "wave_state.json").write_text(json.dumps(OrderedDict([
                ("run_id", run), ("model_id", SIBLING_MODEL), ("variant", variant),
                ("iteration", 2), ("phase", "done")])), encoding="utf-8")
            raw = self.root / "thesis/results/raw" / ("%s__%s__iter2" % (run, variant)) / SIBLING_MODEL
            raw.mkdir(parents=True, exist_ok=True)
            (raw / "generations.jsonl").write_bytes(b'{"sample_id": "s"}\n')
        definitions = self.root / sl.SIBLINGS[run]["definitions"]
        definitions.mkdir(parents=True, exist_ok=True)
        for name in sl.SIBLINGS[run]["definition_files"]:
            (definitions / name).write_text("{}", encoding="utf-8")

    def write_origin_bindings(self):
        """Synthetic recovery_001 contract / authorization / T0 evidence /
        global fragment and definition files, so the REAL predecessor
        bindings are built and verified."""
        from thesis.evaluation import pilot_run_contract as prc

        definitions = self.root / sl.PREDECESSOR_DEFINITIONS_REL
        contract = OrderedDict([("run_id", sl.PREDECESSOR), ("status", "READY"),
                                ("model_ids", list(sl.MODELS) + [ORIGIN_MODEL])])
        contract["contract_sha256"] = prc.contract_sha256(contract)
        (definitions / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
        for name in sl.PREDECESSOR_DEFINITION_FILES:
            if not (definitions / name).exists():
                (definitions / name).write_text(json.dumps({"synthetic": name}), encoding="utf-8")
        fragments = self.root / sl.PREDECESSOR_FRAGMENTS_REL
        fragments.mkdir(parents=True, exist_ok=True)
        documents = {
            "authorization.start.json": {"content_sha256": "1" * 64, "content": {
                "decision": "START_ALLOWED", "run_id": sl.PREDECESSOR,
                "frozen_contract_sha256": contract["contract_sha256"], "authorization_sha256": "a" * 64,
                "fresh_t0_runtime_condition_sha256": "r" * 64}},
            "runtime.evidence.json": {"fingerprint_sha256": "f" * 64, "content": {
                "contract_sha256": contract["contract_sha256"], "repair_condition_sha256": self.repair_condition(),
                "static_analysis_condition_sha256": "s" * 64,
                "provider_endpoint_identities": {m: None for m in sl.MODELS}}},
            "global.json": {"content": {"git_commit": "synthetic", "git_dirty": False}},
        }
        for name, document in documents.items():
            (fragments / name).write_text(json.dumps(document), encoding="utf-8")

    def repair_condition(self):
        from thesis.evaluation import static_provenance

        return static_provenance.repair_condition_sha256(static_provenance.repair_condition(self.config))

    def build(self):
        adapter = FakeAdapter()
        for model_id in sl.MODELS + (ORIGIN_MODEL,):
            self.write_parent(model_id)
        self.parent = self.parent_lineage()
        self.origin_outcomes = {variant: self.run_origin(variant, adapter) for variant in sl.VARIANTS}
        self.write_origin_bindings()
        for run in sl.SIBLINGS:
            self.write_sibling(run)
        snapshot = sh.build_snapshot(self.root)
        view = sh.PredecessorView(sh.Snapshot(self.root, snapshot, snapshot["snapshot_sha256"]))
        refs = sl.parent_refs(self.root)
        origin = OrderedDict()
        for model_id in sl.MODELS:
            for variant in sl.VARIANTS:
                origin["%s/%s" % (model_id, variant)] = sl.loop_origin(self.root, view, refs, self.config,
                                                                      model_id, variant)
        document = OrderedDict([
            ("schema_version", sl.SCHEMA), ("run_id", sl.SUCCESSOR),
            ("predecessor_run_id", sl.PREDECESSOR), ("parent_run_id", sl.PARENT),
            ("pilot_run_id", sl.PILOT), ("model_ids", list(sl.MODELS)),
            ("model_priority", list(sl.MODELS)), ("variants", list(sl.VARIANTS)),
            ("max_iterations", sl.MAX_ITERATIONS), ("provider_iterations", list(sl.PROVIDER_ITERATIONS)),
            ("successor_base_cells", 0), ("policy", sl.POLICY),
            ("predecessor", sl.predecessor_bindings(self.root, view)),
            ("predecessor_snapshot", snapshot),
            ("predecessor_retirement", sl.predecessor_retirement(view)),
            ("sibling_successors", sl.sibling_successors(self.root)),
            ("origin", origin)])
        document["lineage_sha256"] = sl.fingerprint(document)
        self.lineage = sl.SuccessorLineage(self.root, json.loads(json.dumps(document),
                                                                 object_pairs_hook=OrderedDict),
                                           document["lineage_sha256"])

    # -- byte inventory ---------------------------------------------------

    @staticmethod
    def foreign(run):
        return (run == sl.PARENT or run == sl.PREDECESSOR or run.startswith(sl.PREDECESSOR + "__")
                or any(run == s or run.startswith(s + "__") for s in sl.SIBLINGS))

    def inherited_digest(self):
        """sha256 of every parent/origin/sibling byte (everything 004 may only read)."""
        digest = OrderedDict()
        for area in ("raw", "intermediate"):
            base = self.root / "thesis/results" / area
            for path in sorted(p for p in base.rglob("*") if p.is_file()):
                relative = path.relative_to(self.root).as_posix()
                if self.foreign(relative.split("/")[3]):
                    digest[relative] = sha256(path.read_bytes())
        return digest

    def successor_files(self):
        files = []
        for area in ("raw", "intermediate"):
            base = self.root / "thesis/results" / area
            for path in sorted(p for p in base.rglob("*") if p.is_file()):
                relative = path.relative_to(self.root).as_posix()
                run = relative.split("/")[3]
                if run == sl.SUCCESSOR or run.startswith(sl.SUCCESSOR + "__") or run == ".successor_locks":
                    files.append(relative)
                elif not self.foreign(run):
                    raise AssertionError("file outside every registered run: " + relative)
        return files


class ExternalRunner:
    """Mock tool containers: native-shaped merge of mock LLOV/PARCOACH entries
    into the successor iteration static records."""

    def __init__(self, world):
        self.world = world
        self.calls = []
        self.lock = threading.Lock()
        self.tools = {"llov": FakeLLOV(), "parcoach": FakeParcoach()}

    def __call__(self, loop, pending, iteration):
        with self.lock:
            self.calls.append((loop.model_id, loop.variant, iteration, tuple(t for t, _ in pending)))
        settings = self.world.static_settings
        for tool, _count in pending:
            path = loop.paths.stage_path(iteration, "static_analysis")
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
            samples = {s.sample_id: s for s in framework.iter_assembled_samples(
                REPO_ROOT, loop.paths.intermediate_root, loop.paths.iter_run_id(iteration), loop.model_id)}
            for row in rows:
                if tool in row["tools"]:
                    continue
                row["tools"][tool] = ss.measure_entry(self.tools[tool], settings[tool],
                                                      samples[row["sample_id"]], self.world.context,
                                                      row["sample_source_sha256"])
                row["has_blocking_findings"] = rsa.record_has_blocking(row)
                row["low_confidence_count"] = rsa.record_low_confidence_count(row)
                row["analysis_gaps"] = rsa.record_analysis_gaps(row)
            World.write_jsonl(path, rows)
        return []


class StubSuccessorLoop(sr.SuccessorRepairLoop):
    """Real successor loop; only the in-container stages and the provider
    authorization guard are stubbed."""

    world = None
    guard_calls = None
    guard_refusal = None
    events = None

    def _run_analysis_stages(self, iteration, stages):
        if iteration == 0:
            return super()._run_analysis_stages(iteration, stages)  # must refuse
        self.world.write_analyses(self, iteration, stages)

    def provider_guard(self, kind, label=None):
        self.guard_calls.append((self.model_id, self.variant, label))
        if self.guard_refusal is not None:
            raise self.guard_refusal

    def count_request_round(self, sample_ids, iteration):
        result = super().count_request_round(sample_ids, iteration)
        if self.events is not None:
            self.events.append(("intent", self.model_id, self.variant, iteration))
        return result

    def _assemble(self, target_iteration):
        if self.events is not None:
            self.events.append(("assemble", self.model_id, self.variant, target_iteration))
        return super()._assemble(target_iteration)

    def run_external_docker(self, pending, iteration):
        if self.events is not None:
            self.events.append(("external", self.model_id, self.variant, iteration))
        return super().run_external_docker(pending, iteration)

    def log(self, message):
        return None


class SuccessorWorldCase(unittest.TestCase):
    def setUp(self):
        sr.STOP_EVENT.clear()
        del sr.WORKERS[:]
        for lane in list(sr.LANES.snapshot()):
            sr.LANES.reset(lane)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.world.build()
        self.lock = sw.WriterLock(self.world.root, sl.SUCCESSOR, "synthetic-test")
        self.token = self.lock.acquire()
        self.addCleanup(self.lock.release)
        self.authority = FakeAuthority()
        self.external = ExternalRunner(self.world)
        self.adapter = FakeAdapter()
        self.guard_calls = []
        self.events = []
        StubSuccessorLoop.world = self.world
        StubSuccessorLoop.guard_calls = self.guard_calls
        StubSuccessorLoop.guard_refusal = None
        StubSuccessorLoop.events = self.events

    def loops(self, models=None):
        return rs.build_loops(self.world.config, "synthetic.yaml", self.world.lineage, self.world.parent,
                              self.authority, self.token, models=models,
                              adapter_factory=lambda provider: self.adapter,
                              external_runner=self.external, loop_class=StubSuccessorLoop)

    def loop(self, model, variant):
        return [l for l in self.loops([model]) if l.variant == variant][0]

    def drive(self, loops=None, parallel=2, **kwargs):
        clock = kwargs.pop("clock", None) or FakeClock()
        return rs.drive(loops or self.loops(), parallel=parallel, log=quiet, sleep=clock.wait,
                        clock=clock, max_sleep=float("inf"), **kwargs)

    def step_until(self, loop_factory, phase, iteration=None, limit=60):
        for _ in range(limit):
            loop = loop_factory()
            wave = loop.load_wave_state()
            if wave["phase"] == phase and (iteration is None or int(wave["iteration"]) == iteration):
                return loop
            loop.step()
        raise AssertionError("phase %s not reached" % phase)

    def assert_verified(self, loop):
        report = vs.Report(loop.model_id)
        vs.fresh_loop(loop, report, counts())
        self.assertEqual(report.status, "PASS", [c for c in report.checks if c["status"] != "PASS"])


def expected_final(model, variant):
    clean = orchestrator.STATUS_TESTS_PASS if variant == "test_feedback" else orchestrator.STATUS_CLEAN
    return {sample_id(model, "omp", 0): (clean, 1 if variant == "test_feedback" else 2),
            sample_id(model, "omp", 1): (clean, 1),
            sample_id(model, "mpi", 0): (orchestrator.STATUS_BUDGET, 2),
            sample_id(model, "serial", 0): (clean, 0),
            sample_id(model, "omp", 2): (orchestrator.STATUS_UNUSABLE, 0)}


class FixtureTests(SuccessorWorldCase):
    def test_origin_is_fresh_and_the_synthetic_recovery_001_stopped_like_the_real_one(self):
        for variant, outcome in self.world.origin_outcomes.items():
            self.assertEqual(outcome, orchestrator.OUTCOME_DONE if variant == "test_feedback"
                             else orchestrator.OUTCOME_BLOCKED_EXTERNAL)
        for model in sl.MODELS:
            for variant in sl.VARIANTS:
                facts = self.world.lineage.origin(model, variant)
                self.assertEqual((facts["mode"], facts["parent_cells"], facts["parent_assembled"],
                                  facts["parent_unassembled"], facts["predecessor_state"]),
                                 ("FRESH", 5, 4, 1, "ABSENT"))
                if variant != "test_feedback":
                    self.assertEqual(dict(facts["parent_external_missing"]), {"parcoach": 0, "llov": 0})

    def test_origin_refuses_foreign_repair_evidence_and_incomplete_parents(self):
        view = self.world.lineage.view
        refs = sl.parent_refs(self.world.root)
        model = sl.MODELS[0]
        stray = (self.world.root / "thesis/results/intermediate/full_ext_recovery_003" / model
                 / "repair/static_feedback/state.jsonl")
        stray.parent.mkdir(parents=True)
        stray.write_bytes(b"")
        with self.assertRaises(RecoveryRefused):
            sl.loop_origin(self.world.root, view, refs, self.world.config, model, "static_feedback")
        with self.assertRaises(RecoveryRefused):
            self.world.lineage.verify_origin_absence()
        import shutil

        shutil.rmtree(self.world.root / "thesis/results/intermediate/full_ext_recovery_003" / model)
        self.assertTrue(self.world.lineage.verify_origin_absence())
        # a parent artifact that drifted from the parent lineage refuses
        path = self.world.root / "thesis/results/intermediate" / sl.PARENT / model / "assembly.jsonl"
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        with self.assertRaises(RecoveryRefused):
            sl.loop_origin(self.world.root, view, refs, self.world.config, model, "static_feedback")
        path.write_bytes(original)

    def test_methodology_replay_reproduces_recovery_001(self):
        for variant in sl.VARIANTS:
            loop = StubSuccessorLoop(self.world.config, "synthetic.yaml", sl.PROFILE,
                                     self.world.config["profiles"][sl.PROFILE],
                                     self.world.models[ORIGIN_MODEL], variant,
                                     lineage=self.world.lineage, parent_lineage=self.world.parent,
                                     authority=self.authority, replay=True)
            result = loop.replay_origin(self.world.lineage.view)
            self.assertEqual((result["decision_mismatches"], result["request_mismatches"],
                              result["unusable_match"], result["decisions"], result["requests"],
                              result["later_decisions"], result["later_decision_mismatches"]),
                             ([], [], True, 4, 3, 4 if variant == "test_feedback" else 0, []), variant)
            with self.assertRaises(RecoveryRefused):
                loop.step()  # a replay loop never writes

    def test_methodology_replay_detects_a_changed_method(self):
        class AlteredRequests(StubSuccessorLoop):
            def build_request_records(self, target_iteration, sample_ids, history_mode=None):
                rows = super().build_request_records(target_iteration, sample_ids, history_mode)
                for row in rows:
                    row["request"] += "\n(changed feedback rendering)"
                return rows

        class AlteredDecisions(StubSuccessorLoop):
            def compute_decisions(self, iteration):
                decisions = super().compute_decisions(iteration)
                sample, prior, decision = decisions[0]
                decision.stop_reason = "changed stop rule"
                return decisions

        for loop_class, field in ((AlteredRequests, "request_mismatches"),
                                  (AlteredDecisions, "decision_mismatches")):
            loop = loop_class(self.world.config, "synthetic.yaml", sl.PROFILE,
                              self.world.config["profiles"][sl.PROFILE], self.world.models[ORIGIN_MODEL],
                              "static_feedback", lineage=self.world.lineage,
                              parent_lineage=self.world.parent, authority=self.authority, replay=True)
            self.assertTrue(loop.replay_origin(self.world.lineage.view)[field], loop_class.__name__)


class FreshRunTests(SuccessorWorldCase):
    def test_end_to_end_fresh_run(self):
        before = self.world.inherited_digest()
        outcomes = self.drive()
        self.assertEqual(dict(outcomes), {rs.key(l): orchestrator.OUTCOME_DONE for l in self.loops()})
        self.assertEqual(self.world.inherited_digest(), before)
        self.assertTrue(self.world.lineage.snapshot.verify_all())
        self.assertTrue(self.world.lineage.verify_siblings())
        per_model = Counter(m for m, _sha in self.adapter.calls)
        self.assertEqual(per_model, Counter({m: sum(CALLS_PER_MODEL.values()) for m in sl.MODELS}))
        self.assertEqual(len(self.guard_calls), len(self.adapter.calls))
        self.assertEqual(len(set(self.guard_calls)), len(self.guard_calls))  # no sample twice
        by_iteration = Counter((i, tools) for _m, _v, i, tools in self.external.calls)
        self.assertEqual(by_iteration, Counter({(1, ("parcoach", "llov")): 10, (2, ("parcoach", "llov")): 10}))
        for loop in self.loops():
            final = loop.sample_states()
            self.assertEqual({s: (r["status"], r["iteration"]) for s, r in final.items()},
                             expected_final(loop.model_id, loop.variant), rs.key(loop))
            self.assert_verified(loop)
            wave = loop.load_wave_state()
            self.assertEqual((wave["origin"], wave["parent_run_id"], wave["lineage_sha256"]),
                             ("FRESH", sl.PARENT, self.world.lineage.sha256))
        files = self.world.successor_files()
        self.assertTrue(any("__test_feedback__iter1" in f for f in files))
        self.assertFalse([f for f in files if "/supplements/" in f])
        # a second drive is a no-op: no request, no tool run, no new byte
        snapshot = {f: sha256((self.world.root / f).read_bytes()) for f in files}
        calls, tools = len(self.adapter.calls), len(self.external.calls)
        self.assertEqual(set(self.drive().values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual((len(self.adapter.calls), len(self.external.calls)), (calls, tools))
        self.assertEqual({f: sha256((self.world.root / f).read_bytes())
                          for f in self.world.successor_files()}, snapshot)

    def test_iteration_zero_is_decided_from_the_parent_never_measured(self):
        loop = self.step_until(lambda: self.loop(sl.MODELS[0], "combined_feedback"), "requests_built", 1)
        rows = loop.successor_state_rows()
        self.assertEqual(Counter((r["iteration"], r["status"]) for r in rows),
                         Counter({(0, "active"): 3, (0, "stopped_clean"): 1, (0, "repair_unusable"): 1}))
        self.assertEqual(len(loop.load_requests(1)), 3)
        self.assertEqual(self.external.calls, [])
        self.assertFalse((self.world.root / "thesis/results/intermediate"
                          / loop.paths.iter_run_id(1)).exists())
        request = loop.load_requests(1)[0]["request"]
        self.assertIn("use of undeclared identifier 'summ'", request)   # parent feedback
        self.assertIn("return 0.0;", request)                          # parent code

    def test_api_first_v2_orders_waves_and_priorities(self):
        outcomes = self.drive(parallel=1)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        events = self.events

        def index(predicate, last=False):
            matches = [i for i, e in enumerate(events) if predicate(e)]
            return (matches[-1] if last else matches[0]) if matches else None

        last_intent1 = index(lambda e: e[0] == "intent" and e[3] == 1, last=True)
        first_analysis1 = index(lambda e: e[0] in ("assemble", "external") and e[3] == 1)
        last_intent2 = index(lambda e: e[0] == "intent" and e[3] == 2, last=True)
        first_analysis2 = index(lambda e: e[0] in ("assemble", "external") and e[3] == 2)
        self.assertLess(last_intent1, first_analysis1)   # nothing analysed during SUBMIT@1
        self.assertLess(last_intent2, first_analysis2)   # nothing of iteration 2 analysed before the last request
        # SUBMIT@1 with one worker: the Alibaba lane first (variants alternate across its
        # three models), then gemini, then openai - the author's strict priority
        order = []
        for e in events:
            if e[0] == "intent" and e[3] == 1 and (e[1], e[2]) not in order:
                order.append((e[1], e[2]))
        expected = [(m, v) for v in sl.VARIANTS for m in ALIBABA]
        expected += [("gemini_36_flash", v) for v in sl.VARIANTS] + [("openai_gpt56_sol", v) for v in sl.VARIANTS]
        self.assertEqual(order, expected)
        # iteration-2 requests of every loop follow its own iteration-1 decision
        for loop in self.loops():
            first2 = index(lambda e: e[0] == "intent" and e[3] == 2 and e[1:3] == (loop.model_id, loop.variant))
            own1 = index(lambda e: e[0] in ("assemble", "external") and e[3] == 1
                         and e[1:3] == (loop.model_id, loop.variant), last=True)
            if first2 is not None:
                self.assertLess(own1, first2, rs.key(loop))

    def test_priority_order_and_lanes(self):
        loops = self.loops()
        self.assertEqual([rs.key(l) for l in loops][:3],
                         ["deepseek_v4_pro/static_feedback", "qwen36_35b_a3b/static_feedback",
                          "qwen37_max/static_feedback"])
        lanes = {l.model_id: l.lane for l in loops}
        self.assertEqual(len({lanes[m] for m in ALIBABA}), 1)
        self.assertEqual(len(set(lanes.values())), 3)
        self.assertNotIn("http", "".join(lanes.values()))  # configuration names, never values

    def test_restart_after_every_step(self):
        model = sl.MODELS[1]
        steps = 0
        while True:
            loop = self.loop(model, "combined_feedback")  # fresh instance == process restart
            if loop.load_wave_state()["phase"] == "done":
                break
            loop.step()
            steps += 1
            self.assertLess(steps, 60)
        self.assertEqual(len(self.adapter.calls), CALLS_PER_MODEL["combined_feedback"])
        self.assert_verified(loop)

    def test_resume_holds_loops_by_wave(self):
        model = sl.MODELS[0]
        # one loop past its iteration-1 provider phase, one at requests_built@2, the rest fresh
        self.step_until(lambda: self.loop(model, "static_feedback"), "responses_merged", 1)
        self.step_until(lambda: self.loop(model, "combined_feedback"), "requests_built", 2)
        before = len(self.adapter.calls)
        del self.events[:]
        outcomes = self.drive()
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        events = self.events
        last_intent1 = max(i for i, e in enumerate(events) if e[0] == "intent" and e[3] == 1)
        first_analysis1 = min(i for i, e in enumerate(events) if e[0] in ("assemble", "external"))
        self.assertLess(last_intent1, first_analysis1)
        self.assertEqual(len(self.adapter.calls), 5 * sum(CALLS_PER_MODEL.values()))
        self.assertGreater(before, 0)
        for loop in self.loops([model]):
            self.assert_verified(loop)

    def test_crash_between_outcome_and_wave_save_never_resubmits(self):
        model = sl.MODELS[0]
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        loop = self.step_until(factory, "requests_built", 1)
        loop.step()
        self.assertEqual(factory().load_wave_state()["phase"], "responses_merged")
        calls = len(self.adapter.calls)
        loop.save_wave_state(1, "requests_built")  # the crash lost the phase transition
        self.assertEqual(factory().step(), orchestrator.OUTCOME_ADVANCED)
        self.assertEqual(len(self.adapter.calls), calls)
        self.assertEqual(len(factory().submission_intents(1)), 3)

    def test_ambiguous_intent_stops_until_explicitly_resolved(self):
        model = sl.MODELS[0]
        target = sample_id(model, "mpi", 0)
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        self.step_until(factory, "requests_built", 2)
        self.assertEqual(factory().load_requests(2)[0]["sample_id"], target)
        self.adapter.sequence = ["crash"]
        with self.assertRaises(SimulatedCrash):
            factory().step()
        sent = len(self.adapter.calls)
        self.assertTrue(any(r["sample_id"] == target for r in factory().submission_intents(2)))
        with self.assertRaises(sr.SuccessorStop):
            factory().step()
        self.assertEqual(len(self.adapter.calls), sent)  # nothing resubmitted automatically
        outcome = self.drive([factory()])[rs.key(factory())]
        self.assertIsInstance(outcome, sr.SuccessorStop)  # the driver isolates the loop, no resend
        self.assertEqual(len(self.adapter.calls), sent)
        with self.assertRaises(RecoveryRefused):
            factory().resolve_ambiguous(sample_id(model, "omp", 1), "not open", 2)
        with self.assertRaises(RecoveryRefused):
            factory().resolve_ambiguous(target, "wrong iteration", 1)
        intent = factory().resolve_ambiguous(target, "operator: response lost in the crash", 2)
        resolution = [r for r in factory().submission_ledger(2) if r["kind"] == "resolution"]
        self.assertEqual([(r["intent_id"], r["possible_duplicate_billing"]) for r in resolution],
                         [(intent, True)])
        self.assertEqual(set(self.drive([factory()]).values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(factory().counted_rounds(2)[target], 2)  # lost round + one resubmission
        self.assert_verified(factory())

    def test_ambiguous_intent_at_the_bound_ends_natively(self):
        model = sl.MODELS[1]
        target = sample_id(model, "mpi", 0)
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        self.step_until(factory, "requests_built", 1)
        self.assertEqual(factory().load_requests(1)[0]["sample_id"], target)
        self.adapter.sequence = ["error", "ok", "ok", "crash"]
        with self.assertRaises(SimulatedCrash):
            for _ in range(4):
                factory().step()
        sent = len(self.adapter.calls)
        self.assertEqual(set(self.drive([factory()]).values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(len(self.adapter.calls[sent:]), 1)  # iteration 2 of omp_0 only
        self.assertEqual(factory().sample_states()[target]["status"], orchestrator.STATUS_API_EXHAUSTED)
        report = vs.Report(model)
        c = counts()
        vs.fresh_loop(factory(), report, c)
        failing = [x for x in report.checks if x["status"] != "PASS"]
        self.assertEqual([x["check"] for x in failing], ["static_feedback: no request ended by provider exhaustion"])
        self.assertEqual([r["sample_id"] for r in failing[0]["detail"]["outcome_unknown_at_native_bound"]],
                         [target])
        self.assertEqual(c["new"]["iteration1_ambiguous_at_bound"], 1)

    def test_refused_before_send_is_not_a_round(self):
        model = sl.MODELS[0]
        factory = lambda: self.loop(model, "combined_feedback")  # noqa: E731
        self.step_until(factory, "requests_built", 1)
        from thesis.evaluation.run_authorization import PreRunInfrastructureFailure
        StubSuccessorLoop.guard_refusal = PreRunInfrastructureFailure("guard refused")
        with self.assertRaises(PreRunInfrastructureFailure):
            factory().step()
        self.assertEqual(factory().submission_ledger(1), [])  # guard runs before the intent
        StubSuccessorLoop.guard_refusal = None
        self.adapter.sequence = ["chokepoint"]
        with self.assertRaises(PreRunInfrastructureFailure):
            factory().step()
        kinds = [r["kind"] for r in factory().submission_ledger(1)]
        self.assertEqual(kinds, ["intent", "refused_before_send"])
        self.assertEqual(dict(factory().counted_rounds(1)), {})
        self.assertEqual(set(self.drive([factory()]).values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(sorted(factory().counted_rounds(1).values()), [1, 1, 1])
        report = vs.Report(model)
        c = counts()
        vs.fresh_loop(factory(), report, c)
        self.assertEqual(report.status, "PASS", [x for x in report.checks if x["status"] != "PASS"])
        self.assertEqual(c["new"]["iteration1_refused_before_send"], 1)

    def test_recorded_provider_failure_is_requeued_within_the_bound(self):
        model = sl.MODELS[3]  # gemini lane: one failure does not trip the lane
        self.adapter.sequence = ["error"]
        clock = FakeClock()
        loops = [l for l in self.loops([model]) if l.variant == "static_feedback"]
        outcomes = self.drive(loops, parallel=1, clock=clock, api_retry_delay=7.0)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(clock.waits, [7.0])
        loop = self.loop(model, "static_feedback")
        self.assertEqual(sorted(loop.counted_rounds(1).values()), [1, 1, 2])
        failed = loop.paths.iter_generations_path(1).with_name("failed_responses.jsonl")
        self.assertEqual(len(sw.read_jsonl(failed)), 1)  # the recorded failure stays archived
        self.assert_verified(loop)

    def test_provider_outage_pauses_only_its_lane(self):
        self.adapter.fail_models = set(ALIBABA)
        clock = FakeClock()
        outcomes = self.drive(parallel=2, clock=clock, api_retry_delay=600.0)
        alibaba = {k: v for k, v in outcomes.items() if k.split("/")[0] in ALIBABA}
        others = {k: v for k, v in outcomes.items() if k.split("/")[0] not in ALIBABA}
        self.assertEqual(set(others.values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(len(others), 6)
        self.assertEqual(len(alibaba), 9)
        for outcome in alibaba.values():
            self.assertIsInstance(outcome, sr.ProviderPaused)
        alibaba_calls = [c for c in self.adapter.calls if c[0] in ALIBABA]
        self.assertLessEqual(len(alibaba_calls), 5)  # 3 to trip + in-flight + ONE half-open probe
        self.assertIn(600.0, clock.waits)
        for loop in self.loops():
            if loop.model_id in ALIBABA:
                self.assertEqual(loop.load_wave_state()["phase"], "requests_built")
                self.assertFalse([s for s in loop.sample_states().values()
                                  if s["status"] == orchestrator.STATUS_API_EXHAUSTED])
            else:
                self.assert_verified(loop)
        # a half-open probe never spends a sample's last round: no sample has
        # two counted rounds after the outage
        for loop in self.loops(list(ALIBABA)):
            self.assertLessEqual(max(list(loop.counted_rounds(1).values()) or [0]), 1, rs.key(loop))
        # the provider is back: the same command resumes the paused lane
        self.adapter.fail_models = set()
        outcomes = self.drive(parallel=2)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        for loop in self.loops(list(ALIBABA)):
            self.assertLessEqual(max(loop.counted_rounds(1).values()), 2)
            self.assertEqual({s: (r["status"], r["iteration"]) for s, r in loop.sample_states().items()},
                             expected_final(loop.model_id, loop.variant), rs.key(loop))
            self.assert_verified(loop)

    def test_an_outage_after_answers_keeps_the_lane_down_for_the_invocation(self):
        # the first 6 Alibaba answers arrive (deepseek/static, qwen36/static), then the lane fails
        self.adapter.fail_after = (set(ALIBABA), 6)
        clock = FakeClock()
        outcomes = self.drive(parallel=1, clock=clock, api_retry_delay=600.0)
        for name in ("deepseek_v4_pro/static_feedback", "qwen36_35b_a3b/static_feedback"):
            self.assertIsInstance(outcomes[name], sr.ProviderPaused, name)
            self.assertIn(rs.LANE_DOWN, str(outcomes[name]))
            loop = self.loop(*name.split("/"))
            wave = loop.load_wave_state()
            self.assertEqual((wave["phase"], wave["iteration"]), ("requests_built", 2), name)
            self.assertEqual(loop.submission_ledger(2), [], name)  # no iteration-2 request to a down lane
        others = {k: v for k, v in outcomes.items() if k.split("/")[0] not in ALIBABA}
        self.assertEqual(set(others.values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(clock.waits, [600.0])  # one pause per invocation, no second cycle in wave 2
        self.adapter.fail_after = None
        outcomes = self.drive(parallel=2)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        for loop in self.loops(list(ALIBABA)):
            self.assertEqual({s: (r["status"], r["iteration"]) for s, r in loop.sample_states().items()},
                             expected_final(loop.model_id, loop.variant), rs.key(loop))
            self.assert_verified(loop)

    def test_parent_drift_is_a_global_stop(self):
        path = self.world.root / "thesis/results/intermediate" / sl.PARENT / sl.MODELS[0] / "assembly.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(sr.GlobalIntegrityError):
            self.drive()
        self.assertTrue(sr.STOP_EVENT.is_set())
        self.assertEqual(self.adapter.calls, [])

    def test_definition_drift_is_a_global_stop(self):
        loop = self.loop(sl.MODELS[0], "static_feedback")
        loop.step()  # verified and cached
        for relative in (sl.SIBLINGS["full_ext_recovery_003"]["definitions"] + "/contract.json",
                         sl.PREDECESSOR_DEFINITIONS_REL + "/readiness.json"):
            path = self.world.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaises(sr.GlobalIntegrityError, msg=relative):
                self.loop(sl.MODELS[0], "static_feedback").step()
            path.write_bytes(original)

    def test_a_torn_outcome_becomes_a_resolvable_ambiguity(self):
        model = sl.MODELS[3]
        target = sample_id(model, "mpi", 0)
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        self.step_until(factory, "requests_built", 1)
        self.adapter.sequence = ["crash"]
        with self.assertRaises(SimulatedCrash):
            factory().step()
        generations = factory().paths.iter_generations_path(1)
        generations.parent.mkdir(parents=True, exist_ok=True)
        with generations.open("ab") as handle:
            handle.write(b'{"sample_id": "%s", "partial' % target.encode("utf-8"))
        with self.assertRaises(sr.SuccessorStop):
            factory().step()  # archived tail -> an open AMBIGUOUS intent, nothing resubmitted
        self.assertTrue(generations.with_name("generations.jsonl.torn").exists())
        factory().resolve_ambiguous(target, "operator: torn outcome archived", 1)
        self.assertEqual(set(self.drive([factory()]).values()), {orchestrator.OUTCOME_DONE})
        self.assert_verified(factory())

    def test_a_leftover_temp_file_does_not_block_the_fresh_start(self):
        loop = self.loop(sl.MODELS[2], "static_feedback")
        loop.paths.repair_dir.mkdir(parents=True)
        (loop.paths.repair_dir / "wave_state.json.tmp-1-2-x").write_text("{", encoding="utf-8")
        self.assertEqual(self.loop(sl.MODELS[2], "static_feedback").load_wave_state()["phase"], "start")
        (loop.paths.repair_dir / "state.jsonl").write_text("", encoding="utf-8")
        with self.assertRaises(RecoveryRefused):
            self.loop(sl.MODELS[2], "static_feedback").load_wave_state()

    def test_advance_stops_at_a_step_boundary(self):
        loop = self.loop(sl.MODELS[0], "static_feedback")
        sr.STOP_EVENT.set()
        with self.assertRaises(sr.StopRequested):
            rs.advance(loop, 1)
        self.assertEqual(self.world.successor_files(), [sw.LOCK_DIR + "/%s.writer.lock" % sl.SUCCESSOR])

    def test_freeze_labels_name_their_interpreter(self):
        from thesis.recovery_successor_004 import freeze as sf

        self.assertTrue(sf.label_matches("py38", "3.8.0"))
        self.assertTrue(sf.label_matches("py312", "3.12.3"))
        self.assertFalse(sf.label_matches("py38", "3.12.3"))
        self.assertFalse(sf.label_matches("py311", "3.1.1"))

    def test_external_conflict_exits_are_a_global_stop(self):
        from unittest import mock

        loop = self.loop(sl.MODELS[0], "static_feedback")
        loop.external_runner = None  # the real docker path, subprocess mocked
        started = []

        def exiting(code):
            def run(command, **kwargs):
                started.append(command)
                return subprocess.CompletedProcess(command, code)
            return run

        pending = [("parcoach", 1), ("llov", 1)]
        for code in sorted(sx.GLOBAL_CONFLICT_EXITS):
            del started[:]
            with mock.patch.object(sr.subprocess, "run", exiting(code)):
                with self.assertRaises(sr.GlobalIntegrityError, msg=code):
                    loop.run_external_docker(pending, 1)
            self.assertEqual(len(started), 1, code)  # nothing further is started
        for code in (1, sx.EXIT_ENVIRONMENT, 125):  # tool crash / gate / docker: this loop only
            del started[:]
            with mock.patch.object(sr.subprocess, "run", exiting(code)):
                self.assertEqual(loop.run_external_docker(pending, 1), ["parcoach", "llov"], code)
            self.assertEqual(len(started), 2, code)

    def test_a_runtime_conflict_in_a_tool_container_stops_the_whole_run(self):
        from unittest import mock

        loops = self.loops()
        for loop in loops:
            loop.external_runner = None
        conflict = lambda command, **kwargs: subprocess.CompletedProcess(command, sx.EXIT_RUNTIME_CONFLICT)  # noqa: E731
        with mock.patch.object(sr.subprocess, "run", conflict):
            with self.assertRaises(sr.GlobalIntegrityError):
                self.drive(loops)
        self.assertTrue(sr.STOP_EVENT.is_set())
        for loop in self.loops():
            # api_first: every iteration-1 answer is in before the first analysis
            self.assertEqual(loop.load_wave_state()["iteration"], 1, rs.key(loop))
            self.assertEqual(loop.submission_ledger(2), [], rs.key(loop))

    def test_global_failure_stops_every_loop(self):
        self.authority.refuse = True
        with self.assertRaises(sr.GlobalIntegrityError):
            self.drive()
        self.assertTrue(sr.STOP_EVENT.is_set())
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(self.world.successor_files(), [sw.LOCK_DIR + "/%s.writer.lock" % sl.SUCCESSOR])

    def test_operator_abort_stops_every_loop(self):
        loops = self.loops()

        def interrupted():
            raise KeyboardInterrupt()

        loops[0].step = interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.drive(loops)
        self.assertTrue(sr.STOP_EVENT.is_set())
        self.assertEqual(self.adapter.calls, [])

    def test_stop_event_blocks_new_intents(self):
        model = sl.MODELS[0]
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        self.step_until(factory, "requests_built", 1)
        sr.STOP_EVENT.set()
        with self.assertRaises(sr.StopRequested):
            factory().step()
        self.assertEqual(factory().submission_ledger(1), [])
        self.assertEqual(self.adapter.calls, [])

    def test_torn_tails(self):
        model = sl.MODELS[0]
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        loop = self.step_until(factory, "decided", 0)
        requests = loop.paths.requests_path(1)
        requests.parent.mkdir(parents=True, exist_ok=True)
        requests.write_bytes(b'{"partial": ')
        factory().step()
        self.assertTrue(requests.with_name("requests.jsonl.torn").exists())
        self.assertEqual(len(factory().load_requests(1)), 3)
        with loop.paths.state_path.open("ab") as handle:
            handle.write(b'{"torn"')
        with self.assertRaises(RecoveryRefused):
            factory().step()

    def test_protected_drift_and_authority_refuse_before_any_write(self):
        model = sl.MODELS[0]
        loop = self.loop(model, "static_feedback")
        for relative in (sh.repair_dir(ORIGIN_MODEL, "static_feedback") + "/state.jsonl",
                         "thesis/results/intermediate/full_ext_recovery_003/%s/repair/static_feedback/"
                         "wave_state.json" % SIBLING_MODEL):
            path = self.world.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b"\n")
            with self.assertRaises(sr.GlobalIntegrityError):
                loop.step()
            path.write_bytes(original)
        self.authority.refuse = True
        with self.assertRaises(sr.GlobalIntegrityError):
            loop.step()
        self.assertEqual(self.world.successor_files(), [sw.LOCK_DIR + "/%s.writer.lock" % sl.SUCCESSOR])

    def test_guards(self):
        model = sl.MODELS[0]
        loop = self.loop(model, "static_feedback")
        sample = sample_id(model, "omp", 0)
        parent_raw = loop.paths.iter_generations_path(0)
        for call in (lambda: loop._run_analysis_stages(0, ["static"]),
                     lambda: loop._submit(0), lambda: loop._finish_responses(0),
                     lambda: loop._assemble(0), lambda: loop._build_requests(0),
                     lambda: loop._build_requests(3), lambda: loop._submit_batch(1),
                     lambda: loop._poll_batch(1),
                     lambda: loop.save_wave_state(3, "decided"),
                     lambda: loop.save_wave_state(1, "submitted", batch={"id": "x"}),
                     lambda: loop.append_sample_state(sample, 3, "active", "x"),
                     lambda: loop.run_external_docker([("llov", 1)], 0),
                     lambda: loop.external_command("llov", 0),
                     lambda: loop._load_terminal_responses(parent_raw),
                     lambda: loop.submission_ledger(0),
                     lambda: loop.count_request_round([sample], 1)):
            with self.assertRaises(RecoveryRefused):
                call()
        command = loop.external_command("llov", 1)
        self.assertIn("--name pareval-%s-%s-static_feedback-it1-llov" % (sl.SUCCESSOR, model), command)
        self.assertIn("--label %s=%s" % (sr.CONTAINER_LABEL, sl.SUCCESSOR), command)
        self.assertIn("-e %s " % sr.TOKEN_ENV, command)
        self.assertNotIn(self.token, command)
        self.assertIn(" -B -m thesis.recovery_successor_004.external ", command)
        self.assertIn("--target-run-id %s__static_feedback__iter1 " % sl.SUCCESSOR, command)
        self.assertEqual(self.world.successor_files(), [sw.LOCK_DIR + "/%s.writer.lock" % sl.SUCCESSOR])
        with self.assertRaises(RecoveryRefused):
            self.loop(ORIGIN_MODEL, "static_feedback")  # outside the 004 scope

    def test_a_second_fresh_start_is_refused(self):
        model = sl.MODELS[2]
        loop = self.step_until(lambda: self.loop(model, "test_feedback"), "requests_built", 1)
        loop.paths.wave_state_path.unlink()  # a lost wave state with owned artifacts
        with self.assertRaises(RecoveryRefused):
            self.loop(model, "test_feedback").load_wave_state()

    def test_wave_state_must_be_successor_written(self):
        model = sl.MODELS[0]
        loop = self.step_until(lambda: self.loop(model, "static_feedback"), "decided", 0)
        state = json.loads(loop.paths.wave_state_path.read_text(encoding="utf-8"))
        for field in ("lineage_sha256", "origin", "parent_lineage_sha256", "repair_condition_sha256"):
            tampered = dict(state)
            tampered[field] = "x"
            loop.paths.wave_state_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises((RecoveryRefused, RuntimeError)):
                self.loop(model, "static_feedback").load_wave_state()
        loop.paths.wave_state_path.write_text(json.dumps(state), encoding="utf-8")
        self.loop(model, "static_feedback").load_wave_state()

    def test_contract_rebuild_requires_the_writer_token(self):
        from thesis.recovery_successor_004 import contract as sc

        previous = os.environ.pop(sw.TOKEN_ENV, None)
        try:
            with self.assertRaises(RecoveryRefused) as raised:
                sc.build(self.world.root / sl.CONFIG_REL, sl.SUCCESSOR, root=self.world.root)
            self.assertIn("writer lock", str(raised.exception))
            os.environ[sw.TOKEN_ENV] = "0" * 32
            with self.assertRaises(RecoveryRefused):
                sc.build(self.world.root / sl.CONFIG_REL, sl.SUCCESSOR, root=self.world.root)
        finally:
            os.environ.pop(sw.TOKEN_ENV, None)
            if previous is not None:
                os.environ[sw.TOKEN_ENV] = previous


class FakeContainerAuthority:
    def __init__(self):
        self.enforced = []

    def validate(self):
        return {"contract_sha256": FakeAuthority.contract_sha256,
                "authorization_sha256": FakeAuthority.authorization_sha256}

    def enforce(self, tool, model):
        self.enforced.append((tool, model))
        return {"stage_runtime_sha256": "s" * 64, "invocation_sha256": "i" * 64}


class ExternalEntrypointTests(SuccessorWorldCase):
    """external.run: argument routing, writer token, in-flight targets only."""

    def setUp(self):
        super().setUp()
        definitions = self.world.root / sl.DEFINITIONS_REL
        definitions.mkdir(parents=True, exist_ok=True)
        (definitions / "lineage.json").write_text(json.dumps(self.world.lineage.document), encoding="utf-8")
        config_path = self.world.root / sl.CONFIG_REL
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(self.world.config), encoding="utf-8")
        self.previous = os.environ.get(sw.TOKEN_ENV)
        os.environ[sw.TOKEN_ENV] = self.token
        self.addCleanup(self.restore_token)
        from unittest import mock

        settings = self.world.static_settings
        native_calls = self.native_calls = []
        patches = [
            mock.patch.object(sx, "resolve_tool", lambda config, tool: (
                FakeLLOV() if tool == "llov" else FakeParcoach(), {tool: settings[tool]},
                {n: s for n, s in settings.items() if s.enabled})),
            mock.patch.object(sx, "evaluation_context", lambda config: self.world.context),
            mock.patch.object(sx, "run_native", lambda *args, **kwargs: native_calls.append(args[3]) or 0),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def restore_token(self):
        os.environ.pop(sw.TOKEN_ENV, None)
        if self.previous is not None:
            os.environ[sw.TOKEN_ENV] = self.previous

    def args(self, **overrides):
        import argparse

        values = dict(config=sl.CONFIG_REL, profile=sl.PROFILE, run_id=sl.SUCCESSOR,
                      target_run_id="%s__static_feedback__iter1" % sl.SUCCESSOR,
                      model_id=sl.MODELS[0], variant="static_feedback", iteration=1, tool="llov")
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_native_mode_only_for_the_in_flight_iteration(self):
        authority = FakeContainerAuthority()
        with self.assertRaises(RecoveryRefused):  # no wave yet: nothing is in flight
            sx.run(self.args(), root=self.world.root, authority=authority, log=quiet)
        loop = self.loop(sl.MODELS[0], "static_feedback")
        self.step_until(lambda: self.loop(sl.MODELS[0], "static_feedback"), "assembled", 1)
        self.assertEqual(sx.run(self.args(), root=self.world.root, authority=authority, log=quiet), 0)
        self.assertEqual(self.native_calls, ["%s__static_feedback__iter1" % sl.SUCCESSOR])
        with self.assertRaises(RecoveryRefused):  # iteration 2 is not in flight
            sx.run(self.args(iteration=2, target_run_id="%s__static_feedback__iter2" % sl.SUCCESSOR),
                   root=self.world.root, authority=authority, log=quiet)
        self.assertTrue(loop)

    def test_refusals_before_any_write(self):
        authority = FakeContainerAuthority()
        self.step_until(lambda: self.loop(sl.MODELS[0], "static_feedback"), "assembled", 1)
        refused = [
            self.args(iteration=0, target_run_id=sl.SUCCESSOR),
            self.args(target_run_id=sl.PARENT),
            self.args(target_run_id=sh.predecessor_iteration_run("static_feedback", 1)),
            self.args(variant="test_feedback", target_run_id="%s__test_feedback__iter1" % sl.SUCCESSOR),
            self.args(model_id=ORIGIN_MODEL),
            self.args(run_id=sl.PREDECESSOR),
            self.args(iteration=3, target_run_id="%s__static_feedback__iter3" % sl.SUCCESSOR),
        ]
        for args in refused:
            with self.assertRaises(RecoveryRefused):
                sx.run(args, root=self.world.root, authority=authority, log=quiet)
        os.environ[sw.TOKEN_ENV] = "0" * 32
        with self.assertRaises(RecoveryRefused):
            sx.run(self.args(), root=self.world.root, authority=authority, log=quiet)
        self.assertEqual((authority.enforced, self.native_calls), ([], []))

    def test_exit_codes_separate_conflicts_from_tool_failures(self):
        import contextlib
        import io
        from unittest import mock

        from thesis.evaluation import effective_invocation, stage_runtime
        from thesis.evaluation import static_provenance as provenance

        argv = ["--config", sl.CONFIG_REL, "--profile", sl.PROFILE, "--run-id", sl.SUCCESSOR,
                "--target-run-id", "%s__static_feedback__iter1" % sl.SUCCESSOR,
                "--model-id", sl.MODELS[0], "--variant", "static_feedback", "--iteration", "1",
                "--tool", "llov"]
        cases = [
            (stage_runtime.StageRuntimeDrift("static.llov", "tool", "a", "b", ["image"]),
             sx.EXIT_RUNTIME_CONFLICT),
            (effective_invocation.InvocationRefused("drift"), sx.EXIT_RUNTIME_CONFLICT),
            (RecoveryRefused("refused"), sx.EXIT_REFUSED),
            (provenance.StaticMergeConflict("conflict"), sx.EXIT_MERGE_CONFLICT),
            (EnvironmentError("ENVIRONMENT GATE FAILED"), sx.EXIT_ENVIRONMENT),
        ]
        for error, code in cases:
            def raising(args, error=error):
                raise error
            with mock.patch.object(sx, "run", raising), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sx.main(argv), code, type(error).__name__)
        self.assertEqual(sorted(sx.GLOBAL_CONFLICT_EXITS),
                         sorted([sx.EXIT_MERGE_CONFLICT, sx.EXIT_REFUSED, sx.EXIT_RUNTIME_CONFLICT]))
        self.assertNotIn(sx.EXIT_ENVIRONMENT, sx.GLOBAL_CONFLICT_EXITS)


class WriterLockTests(unittest.TestCase):
    def test_single_writer_without_takeover(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = sw.WriterLock(tmp, sl.SUCCESSOR, "a")
            token = first.acquire()
            with self.assertRaises(RecoveryRefused):
                sw.WriterLock(tmp, sl.SUCCESSOR, "b").acquire()
            self.assertTrue(sw.require_token(tmp, sl.SUCCESSOR, token))
            for wrong in (None, "", "0" * 32):
                with self.assertRaises(RecoveryRefused):
                    sw.require_token(tmp, sl.SUCCESSOR, wrong)
            first.release()
            with self.assertRaises(RecoveryRefused):
                sw.require_token(tmp, sl.SUCCESSOR, token)

    def test_another_successor_lock_refuses_the_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = sw.WriterLock(tmp, "full_ext_recovery_003", "other run")
            other.acquire()
            with self.assertRaises(RecoveryRefused):
                rs.require_no_other_writer(Path(tmp))
            other.release()
            self.assertTrue(rs.require_no_other_writer(Path(tmp)))

    def test_lock_path_is_not_version_controlled(self):
        relative = sw.lock_path(".", sl.SUCCESSOR).as_posix().lstrip("./")
        result = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(REPO_ROOT),
                                 "check-ignore", "-q", relative], capture_output=True)
        if result.returncode == 128:
            self.skipTest("git unavailable")
        self.assertEqual(result.returncode, 0, relative)


class LaneMonitorTests(unittest.TestCase):
    def test_trip_reopen_and_close(self):
        monitor = sr.LaneMonitor()
        for _ in range(sr.LANE_TRIP_FAILURES - 1):
            monitor.failure("x")
        self.assertFalse(monitor.tripped("x"))
        monitor.failure("x")
        self.assertTrue(monitor.tripped("x"))
        monitor.reopen("x")
        self.assertFalse(monitor.tripped("x"))
        monitor.failure("x")
        self.assertTrue(monitor.tripped("x"))  # half-open: one failure trips
        monitor.reopen("x")
        monitor.success("x")
        monitor.failure("x")
        self.assertFalse(monitor.tripped("x"))  # closed again after a healthy answer

    def test_lane_adapter_classifies_outcomes(self):
        monitor_before = sr.LANES.snapshot()

        class Inner:
            default_api_key_env = "K"

            def __init__(self, error=None):
                self.error = error

            def generate(self):
                if self.error is not None:
                    raise self.error
                return "answer"

        lane = "test|lane"
        sr.LANES.reset(lane)
        for error in (RuntimeError("x"), RuntimeError("y")):
            with self.assertRaises(RuntimeError):
                sr.LaneAdapter(Inner(error), lane).generate()
        self.assertEqual(sr.LANES.snapshot()[lane]["consecutive_failures"], 2)
        with self.assertRaises(common.ModelRefusal):
            sr.LaneAdapter(Inner(common.ModelRefusal("no")), lane).generate()
        self.assertEqual(sr.LANES.snapshot()[lane]["consecutive_failures"], 0)
        self.assertEqual(sr.LaneAdapter(Inner(), lane).generate(), "answer")
        self.assertEqual(sr.LaneAdapter(Inner(), lane).default_api_key_env, "K")
        sr.LANES.reset(lane)
        self.assertTrue(monitor_before is not None)


class PoolTests(unittest.TestCase):
    """SubmissionPool lane logic with scripted loops (no world, no provider)."""

    class ScriptedLoop:
        def __init__(self, variant, lane, script):
            self.model_id = sl.MODELS[0]
            self.variant = variant
            self.lane = lane
            self.script = list(script)
            self.steps = 0

        def step(self):
            self.steps += 1
            return self.script.pop(0)()

    def setUp(self):
        sr.STOP_EVENT.clear()
        self.lane = "test|pool"
        sr.LANES.reset(self.lane)

    def test_a_late_pre_pause_failure_is_no_failed_probe(self):
        clock = FakeClock()
        outcomes, lock, log = OrderedDict(), threading.Lock(), []
        pool = rs.SubmissionPool(1, 2, outcomes, lock, log.append, 10.0, clock, clock.wait, float("inf"),
                                 {self.lane: 0})
        lane = self.lane
        b_in_flight = threading.Event()
        paused = threading.Event()

        def trip():
            b_in_flight.wait(10)  # B's request is in flight before the lane trips
            for _ in range(sr.LANE_TRIP_FAILURES):
                sr.LANES.failure(lane)
            return sr.ProviderPaused("tripped")

        def late_failure():
            # a request started before the trip returns after the pause expired
            b_in_flight.set()
            import time
            for _ in range(4000):
                with pool.cond:
                    until = pool.lanes.get(lane, {}).get("paused_until")
                if until is not None:
                    break
                time.sleep(0.005)
            self.assertIsNotNone(until)
            paused.set()
            with clock.lock:
                clock.now = until + 5.0
            sr.LANES.failure(lane)
            return sr.ProviderPaused("late")

        def ok():
            sr.LANES.success(lane)
            return orchestrator.OUTCOME_ADVANCED

        loops = [self.ScriptedLoop("static_feedback", lane, [trip, ok]),
                 self.ScriptedLoop("test_feedback", lane, [late_failure, ok]),
                 self.ScriptedLoop("combined_feedback", lane, [ok])]
        pool.start()
        for loop in loops:
            pool.submit(loop)
        pool.close()
        advanced = pool.join()
        self.assertEqual(sorted(l.variant for l in advanced), sorted(sl.VARIANTS))
        self.assertEqual(dict(outcomes), {})
        self.assertFalse([line for line in log if "DOWN" in line])
        self.assertTrue([line for line in log if "re-opened" in line])
        self.assertEqual([l.steps for l in loops], [2, 2, 1])


class StaticSourceTests(unittest.TestCase):
    MODULES = tuple("thesis/recovery_successor_004/%s.py" % name for name in (
        "routing", "run", "external", "contract", "lineage", "handoff", "equivalence", "verify",
        "readiness", "freeze", "preflight", "census")) + ("thesis/evaluation/successor_writer.py",)

    def test_no_successor_path_uses_the_predecessor_contract_builder(self):
        for relative in self.MODULES:
            tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names.add(node.module or "")
                    names.update(alias.name for alias in node.names)
                elif isinstance(node, ast.Import):
                    names.update(alias.name for alias in node.names)
            self.assertFalse([n for n in names if "recovery_contract" in n or n == "run_repair"
                              or "recovery_successor_003" in n], relative)

    def test_no_new_pinned_edit(self):
        from thesis.recovery_successor_004 import equivalence as se

        self.assertEqual(list(se.ROUTING_CHANGES), ["thesis/evaluation/pilot_run_contract.py"])
        text = (REPO_ROOT / "thesis/evaluation/pilot_run_contract.py").read_text(encoding="utf-8")
        self.assertIn('if profile_name.startswith("recovery_successor_"):', text)
        self.assertEqual(sl.PROFILE, "recovery_successor_004")
        self.assertEqual(sl.MODELS, ("deepseek_v4_pro", "qwen36_35b_a3b", "qwen37_max", "gemini_36_flash",
                                     "openai_gpt56_sol"))

    def test_generic_dispatch_resolves_this_package_only(self):
        from thesis.evaluation import pilot_run_contract as prc

        for profile in ("recovery_successor_04", "recovery_successor_004x", "recovery_successor_../x"):
            with self.assertRaises(ValueError):
                prc.build_contract("thesis/config/recovery_successor_004.yaml", profile)

    def test_config_differs_from_003_only_in_profile_and_readiness(self):
        a = json.loads((REPO_ROOT / "thesis/config/recovery_successor_003.yaml").read_text(encoding="utf-8"))
        b = json.loads((REPO_ROOT / sl.CONFIG_REL).read_text(encoding="utf-8"))
        self.assertEqual(sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k)), ["outputs", "profiles"])
        self.assertEqual(b["profiles"][sl.PROFILE]["selection"], "parent_reference_fresh")
        self.assertEqual({k: v for k, v in a["outputs"].items() if k != "readiness_artifact"},
                         {k: v for k, v in b["outputs"].items() if k != "readiness_artifact"})


if __name__ == "__main__":
    unittest.main()
