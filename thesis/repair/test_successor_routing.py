"""Synthetic end-to-end tests of the successor continuation (full_ext_recovery_002).

No provider, no analysis tool, no authorization, no repository result file is
touched: every test builds its own world in a temporary directory.

The synthetic PREDECESSOR is produced by the NATIVE orchestrator.RepairLoop
(iteration 0 routed to a synthetic full_ext_001, as recovery_001 did) and
stopped exactly where recovery_001 stopped: static/combined at iteration 1 in
analyzed_waiting_external with LLOV missing (the LLOV gate refused), and
test_feedback done. The successor then continues it through the real
SuccessorRepairLoop / run_successor.drive with a mock provider, a mock LLOV /
PARCOACH (entries produced by the real supplement code) and stubbed internal
analyses, and the result is checked by the real per-loop verifier.

Run (main container, Python 3.12):
    python3 -B -m unittest thesis.repair.test_successor_routing
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
import unittest
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import framework  # noqa: E402
from thesis.evaluation import recovery_lineage as rl  # noqa: E402
from thesis.evaluation import run_static_analysis as rsa  # noqa: E402
from thesis.evaluation import successor_external as sx  # noqa: E402
from thesis.evaluation import successor_handoff as sh  # noqa: E402
from thesis.evaluation import successor_lineage as sl  # noqa: E402
from thesis.evaluation import successor_supplement as ss  # noqa: E402
from thesis.evaluation import successor_writer as sw  # noqa: E402
from thesis.evaluation import tools as tool_module  # noqa: E402
from thesis.evaluation import verify_successor_run as vs  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused  # noqa: E402
from thesis.evaluation.tool_config import resolve_tool_settings  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.repair import orchestrator  # noqa: E402
from thesis.repair import run_successor as rs  # noqa: E402
from thesis.repair import successor_routing as sr  # noqa: E402
from thesis.repair.test_orchestrator import FIXED_ANSWER, PROMPT_TEXT  # noqa: E402

KEY_ENV = "FAKE_SUCCESSOR_KEY"
# (execution model, sample index, assembled at iteration 0)
SPECS = (("omp", 0, True), ("omp", 1, True), ("mpi", 0, True), ("serial", 0, True),
         ("omp", 2, False))


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


class FakeAdapter:
    """Mock provider: records every request; 'ok' answers FIXED_ANSWER."""

    provider = "openai_compatible"
    default_api_key_env = KEY_ENV

    def __init__(self):
        self.calls = []
        # behaviours consumed per call in submission order (a loop submits its
        # requests sorted by sample id: mpi_sample_0 before omp_sample_0)
        self.sequence = []

    def create_client(self, model_config, api_key, timeout_seconds=None):
        return object()

    def generation_parameters(self, model_config, generation_defaults):
        return {"fake": True}

    def generate(self, client, model_config, generation_defaults, system_prompt, messages,
                 retry_attempts, sleep_seconds):
        text = messages[0]["content"]
        self.calls.append((model_config["id"], sha256(text.encode("utf-8"))))
        behaviour = self.sequence.pop(0) if self.sequence else "ok"
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


class SimulatedCrash(BaseException):
    """A BaseException like KeyboardInterrupt/SystemExit: nothing catches it."""


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


class World:
    """Synthetic parent (full_ext_001) + predecessor (recovery_001) tree."""

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
            if model["id"] in sl.MODELS:
                model["api_key_env"] = KEY_ENV
        self.config = config
        self.static_settings = resolve_tool_settings(config, "static_analysis")
        self.dynamic_settings = {n: s for n, s in resolve_tool_settings(config, "dynamic_analysis").items()
                                 if s.enabled}
        self.models = {m["id"]: m for m in config["models"] if m["id"] in sl.MODELS}
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
            ("historical_repair_policy", "EXCLUDE_ALL_PARENT_REPAIR"), ("model_ids", list(sl.MODELS)),
            ("artifacts", artifacts)])
        document["lineage_sha256"] = rl.fingerprint(document)
        return rl.RecoveryLineage(self.root, document, document["lineage_sha256"])

    # -- predecessor (native loop) ----------------------------------------

    def run_predecessor(self, model_id, variant, adapter):
        world = self

        class PredecessorPaths(orchestrator.LoopPaths):
            def iter_run_id(self, iteration):
                return sl.PARENT if iteration == 0 else super().iter_run_id(iteration)

        class PredecessorLoop(orchestrator.RepairLoop):
            def _run_analysis_stages(self, iteration, stages):
                assert iteration >= 1
                externals = () if self.variant == "test_feedback" else ("parcoach",)
                world.write_analyses(self, iteration, stages, externals)

            def run_external_docker(self, pending, iteration):
                return [tool for tool, _count in pending]  # the LLOV gate refused

            def log(self, message):
                return None

        loop = PredecessorLoop(self.config, "synthetic.yaml", "recovery", {"run_id": sl.PREDECESSOR},
                               self.models[model_id], variant, "g++", lambda provider: adapter)
        loop.paths = PredecessorPaths(self.config, sl.PREDECESSOR, model_id, variant)
        for _ in range(60):
            outcome = loop.step()
            if outcome in (orchestrator.OUTCOME_DONE, orchestrator.OUTCOME_BLOCKED_EXTERNAL):
                return outcome
        raise AssertionError("synthetic predecessor did not settle")

    def build(self):
        adapter = FakeAdapter()
        for model_id in sl.MODELS:
            self.write_parent(model_id)
        self.parent = self.parent_lineage()
        outcomes = {}
        for model_id in sl.MODELS:
            for variant in sl.VARIANTS:
                outcomes[(model_id, variant)] = self.run_predecessor(model_id, variant, adapter)
        self.predecessor_calls = len(adapter.calls)
        snapshot = sh.build_snapshot(self.root)
        view = sh.PredecessorView(sh.Snapshot(self.root, snapshot, snapshot["snapshot_sha256"]))
        handoff = OrderedDict()
        for model_id in sl.MODELS:
            for variant in sl.VARIANTS:
                handoff["%s/%s" % (model_id, variant)] = sl.loop_handoff(view, self.config, model_id, variant)
        document = OrderedDict([
            ("schema_version", sl.SCHEMA), ("run_id", sl.SUCCESSOR),
            ("predecessor_run_id", sl.PREDECESSOR), ("parent_run_id", sl.PARENT),
            ("pilot_run_id", sl.PILOT), ("model_ids", list(sl.MODELS)),
            ("variants", list(sl.VARIANTS)), ("max_iterations", sl.MAX_ITERATIONS),
            ("successor_base_cells", 0), ("policy", sl.POLICY),
            ("predecessor", OrderedDict([("contract_sha256", "0" * 64),
                                         ("parent_lineage_sha256", self.parent.document["lineage_sha256"]),
                                         ("git_commit", "synthetic"), ("git_dirty", False)])),
            ("predecessor_snapshot", snapshot),
            ("predecessor_retirement", sl.predecessor_retirement(view)),
            ("handoff", handoff)])
        document["lineage_sha256"] = sl.fingerprint(document)
        self.lineage = sl.SuccessorLineage(self.root, json.loads(json.dumps(document),
                                                                 object_pairs_hook=OrderedDict),
                                           document["lineage_sha256"])
        return outcomes

    # -- byte inventory ---------------------------------------------------

    def inherited_digest(self):
        """sha256 of every parent/predecessor byte (everything the successor
        may only read)."""
        digest = OrderedDict()
        for area in ("raw", "intermediate"):
            base = self.root / "thesis/results" / area
            for path in sorted(p for p in base.rglob("*") if p.is_file()):
                relative = path.relative_to(self.root).as_posix()
                run = relative.split("/")[3]
                if run == sl.PARENT or run == sl.PREDECESSOR or run.startswith(sl.PREDECESSOR + "__"):
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
                elif not (run == sl.PARENT or run == sl.PREDECESSOR or run.startswith(sl.PREDECESSOR + "__")):
                    raise AssertionError("file outside every registered run: " + relative)
        return files


class ExternalRunner:
    """Mock tool containers: iteration 1 = the REAL supplement writer with a
    mock LLOV; iteration 2 = native-shaped merge of mock LLOV/PARCOACH entries."""

    def __init__(self, world, token, authority):
        self.world = world
        self.token = token
        self.authority = authority
        self.calls = []
        self.tools = {"llov": FakeLLOV(), "parcoach": FakeParcoach()}

    def __call__(self, loop, pending, iteration):
        self.calls.append((loop.model_id, loop.variant, iteration, tuple(t for t, _ in pending)))
        settings = self.world.static_settings
        for tool, _count in pending:
            if iteration == 1:
                sx.run_supplement(self.world.root, self.world.lineage, self.world.config, loop.model_id,
                                  loop.variant, tool,
                                  {"contract_sha256": self.authority.contract_sha256,
                                   "authorization_sha256": self.authority.authorization_sha256},
                                  {"stage_runtime_sha256": None, "invocation_sha256": None},
                                  self.tools[tool], settings[tool], self.world.context, self.token,
                                  log=quiet)
                continue
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

    def _run_analysis_stages(self, iteration, stages):
        if iteration < sr.TARGET_ITERATION:
            return super()._run_analysis_stages(iteration, stages)  # must refuse
        self.world.write_analyses(self, iteration, stages)

    def provider_guard(self, kind, label=None):
        self.guard_calls.append((self.model_id, self.variant, label))
        if self.guard_refusal is not None:
            raise self.guard_refusal

    def log(self, message):
        return None


class SuccessorWorldCase(unittest.TestCase):
    def setUp(self):
        sr.STOP_EVENT.clear()
        del sr.WORKERS[:]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.predecessor_outcomes = self.world.build()
        self.lock = sw.WriterLock(self.world.root, sl.SUCCESSOR, "synthetic-test")
        self.token = self.lock.acquire()
        self.addCleanup(self.lock.release)
        self.authority = FakeAuthority()
        self.external = ExternalRunner(self.world, self.token, self.authority)
        self.adapter = FakeAdapter()
        self.guard_calls = []
        StubSuccessorLoop.world = self.world
        StubSuccessorLoop.guard_calls = self.guard_calls
        StubSuccessorLoop.guard_refusal = None

    def loops(self, models=None, replay=False):
        return rs.build_loops(self.world.config, "synthetic.yaml", self.world.lineage, self.world.parent,
                              self.authority, self.token, models=models,
                              adapter_factory=lambda provider: self.adapter,
                              external_runner=self.external, loop_class=StubSuccessorLoop)

    def loop(self, model, variant):
        return [l for l in self.loops([model]) if l.variant == variant][0]

    def drive(self, loops=None, parallel=2):
        return rs.drive(loops or self.loops(), parallel=parallel, log=quiet, sleep=quiet)

    def step_until(self, loop_factory, phase, iteration=None, limit=40):
        for _ in range(limit):
            loop = loop_factory()
            wave = loop.load_wave_state()
            if wave["phase"] == phase and (iteration is None or int(wave["iteration"]) == iteration):
                return loop
            loop.step()
        raise AssertionError("phase %s not reached" % phase)


class FixtureTests(SuccessorWorldCase):
    def test_predecessor_stops_where_recovery_001_stopped(self):
        for (model, variant), outcome in self.predecessor_outcomes.items():
            facts = self.world.lineage.handoff(model, variant)
            if variant in sl.ADOPT_DONE_VARIANTS:
                self.assertEqual((outcome, facts["mode"], facts["wave_phase"]),
                                 (orchestrator.OUTCOME_DONE, "ADOPT_DONE", "done"))
            else:
                self.assertEqual((outcome, facts["mode"], facts["wave_phase"], facts["wave_iteration"]),
                                 (orchestrator.OUTCOME_BLOCKED_EXTERNAL, "CONTINUE",
                                  "analyzed_waiting_external", 1))
                self.assertEqual(facts["iteration_1"]["external_missing"], {"parcoach": 0, "llov": 2})

    def test_replay_gate_rebuilds_every_predecessor_request(self):
        for model in sl.MODELS:
            for variant in sl.VARIANTS:
                loop = StubSuccessorLoop(self.world.config, "synthetic.yaml", sl.PROFILE,
                                         self.world.config["profiles"][sl.PROFILE],
                                         self.world.models[model], variant,
                                         lineage=self.world.lineage, parent_lineage=self.world.parent,
                                         authority=self.authority, replay=True)
                result = loop.replay_requests(1)
                self.assertEqual(result["requests"], 3)
                self.assertEqual(result["mismatches"], [])
                with self.assertRaises(RecoveryRefused):
                    loop.step()


class ContinuationTests(SuccessorWorldCase):
    def test_end_to_end_continuation(self):
        before = self.world.inherited_digest()
        outcomes = self.drive()
        self.assertEqual(dict(outcomes), {"%s/%s" % (m, v): orchestrator.OUTCOME_DONE
                                          for m in sl.MODELS for v in sl.CONTINUE_VARIANTS})
        self.assertEqual(self.world.inherited_digest(), before)
        self.assertTrue(self.world.lineage.snapshot.verify_all())
        # exactly the active iteration-2 requests, each once, each guarded
        per_model = Counter(m for m, _sha in self.adapter.calls)
        self.assertEqual(per_model, Counter({m: 4 for m in sl.MODELS}))
        self.assertEqual(len(self.guard_calls), len(self.adapter.calls))
        self.assertEqual(len(set(self.guard_calls)), len(self.guard_calls))  # no sample twice
        # external tools: LLOV supplement at iteration 1; LLOV + PARCOACH natively at 2
        by_iteration = Counter((i, tools) for _m, _v, i, tools in self.external.calls)
        self.assertEqual(by_iteration, Counter({(1, ("llov",)): 4, (2, ("parcoach", "llov")): 4}))
        for loop in self.loops():
            final = loop.sample_states()
            m = loop.model_id
            self.assertEqual({s: (r["status"], r["iteration"]) for s, r in final.items()}, {
                sample_id(m, "omp", 0): (orchestrator.STATUS_CLEAN, 2),
                sample_id(m, "omp", 1): (orchestrator.STATUS_CLEAN, 1),
                sample_id(m, "mpi", 0): (orchestrator.STATUS_BUDGET, 2),
                sample_id(m, "serial", 0): (orchestrator.STATUS_CLEAN, 0),
                sample_id(m, "omp", 2): (orchestrator.STATUS_UNUSABLE, 0)})
            supplement = loop.supplement_rows("llov")
            self.assertEqual(len(supplement), 3)  # every assembled iteration-1 sample
            self.assertEqual(Counter(r["entry"]["analysis_state"] for r in supplement),
                             Counter({"COMPLETED": 2, "NOT_APPLICABLE": 1}))
            report = vs.Report(m)
            counts = OrderedDict([("reused", Counter()), ("new", Counter())])
            vs.continued_loop(loop, report, counts)
            self.assertEqual(report.status, "PASS", [c for c in report.checks if c["status"] != "PASS"])
            self.assertEqual(counts["new"]["iteration2_requests"], 2)
            self.assertEqual(counts["new"]["iteration2_submission_intents"], 2)
        for model in sl.MODELS:
            report = vs.Report(model)
            counts = OrderedDict([("reused", Counter()), ("new", Counter())])
            vs.adopted_loop(self.world.lineage, self.world.config, model, "test_feedback", report, counts)
            self.assertEqual(report.status, "PASS", report.checks)
        # every successor write is successor-owned; nothing else appeared
        files = self.world.successor_files()
        self.assertTrue(files)
        self.assertFalse([f for f in files if "/test_feedback" in f or "__test_feedback__" in f])
        # a second drive is a no-op: no request, no tool run, no new byte
        snapshot = {f: sha256((self.world.root / f).read_bytes()) for f in files}
        calls, tools = len(self.adapter.calls), len(self.external.calls)
        self.assertEqual(set(self.drive().values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual((len(self.adapter.calls), len(self.external.calls)), (calls, tools))
        self.assertEqual({f: sha256((self.world.root / f).read_bytes())
                          for f in self.world.successor_files()}, snapshot)

    def test_requests_carry_the_inherited_history(self):
        self.drive()
        loop = self.loop(sl.MODELS[0], "static_feedback")
        requests = {r["sample_id"]: r for r in loop.load_requests(2)}
        request = requests[sample_id(loop.model_id, "omp", 0)]["request"]
        self.assertIn("Iteration 1 (previous attempt)", request)   # parent iteration 0
        self.assertIn("data race on 'sum'", request)               # LLOV supplement at iteration 1
        self.assertIn("return 0.0;", request)                      # parent code in the history
        self.assertIn("sum += x[i];", request)                     # predecessor answer = current code

    def test_restart_after_every_step(self):
        model = sl.MODELS[1]
        steps = 0
        while True:
            loop = self.loop(model, "combined_feedback")  # fresh instance == process restart
            if loop.load_wave_state()["phase"] == "done":
                break
            loop.step()
            steps += 1
            self.assertLess(steps, 40)
        self.assertEqual(len(self.adapter.calls), 2)
        report = vs.Report(model)
        vs.continued_loop(loop, report, OrderedDict([("reused", Counter()), ("new", Counter())]))
        self.assertEqual(report.status, "PASS", [c for c in report.checks if c["status"] != "PASS"])

    def test_crash_between_outcome_and_wave_save_never_resubmits(self):
        model = sl.MODELS[0]
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        loop = self.step_until(factory, "requests_built", 2)
        loop.step()
        self.assertEqual(factory().load_wave_state()["phase"], "responses_merged")
        calls = len(self.adapter.calls)
        loop.save_wave_state(2, "requests_built")  # the crash lost the phase transition
        self.assertEqual(factory().step(), orchestrator.OUTCOME_ADVANCED)
        self.assertEqual(len(self.adapter.calls), calls)
        self.assertEqual(len(factory().submission_intents()), 2)

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
        intents = factory().submission_intents()
        self.assertTrue(any(r["sample_id"] == target for r in intents))
        with self.assertRaises(sr.SuccessorStop):
            factory().step()
        self.assertEqual(len(self.adapter.calls), sent)  # nothing resubmitted automatically
        with self.assertRaises(RecoveryRefused):
            factory().resolve_ambiguous(sample_id(model, "omp", 1), "not open")
        intent = factory().resolve_ambiguous(target, "operator: response lost in the crash")
        resolution = [r for r in factory().submission_ledger() if r["kind"] == "resolution"]
        self.assertEqual([(r["intent_id"], r["possible_duplicate_billing"]) for r in resolution],
                         [(intent, True)])
        outcomes = self.drive()
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        rounds = factory().counted_rounds()
        self.assertEqual(rounds[target], 2)  # the lost round + one resubmission, native bound 2
        report = vs.Report(model)
        vs.continued_loop(factory(), report, OrderedDict([("reused", Counter()), ("new", Counter())]))
        self.assertEqual(report.status, "PASS", [c for c in report.checks if c["status"] != "PASS"])

    def test_ambiguous_intent_at_the_bound_ends_natively(self):
        model = sl.MODELS[1]
        target = sample_id(model, "mpi", 0)
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        self.step_until(factory, "requests_built", 2)
        self.assertEqual(factory().load_requests(2)[0]["sample_id"], target)
        self.adapter.sequence = ["error", "ok", "crash"]
        with self.assertRaises(SimulatedCrash):
            for _ in range(4):
                factory().step()
        # round 1 = recorded transport error, round 2 = in flight when killed:
        # the bound is reached, the native exhaust rule ends the sample without a request
        sent = len(self.adapter.calls)
        self.assertEqual(set(self.drive([factory()]).values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(len(self.adapter.calls), sent)
        self.assertEqual(factory().sample_states()[target]["status"], orchestrator.STATUS_API_EXHAUSTED)
        # provider exhaustion is never a PASS: the verifier STOPs on exactly that
        report = vs.Report(model)
        vs.continued_loop(factory(), report, OrderedDict([("reused", Counter()), ("new", Counter())]))
        failing = [c["check"] for c in report.checks if c["status"] != "PASS"]
        self.assertEqual(failing, ["static_feedback: no request ended by provider exhaustion"])

    def test_api_first_schedule_orders_phases_across_loops(self):
        """Schedule api_first.v1: every iteration-1 analysis precedes the first
        provider request, and EVERY provider request - including the re-queued
        round of a loop with a recorded failure - precedes the first assembly or
        iteration-2 tool run of ANY loop."""
        events = []
        real_generate = self.adapter.generate

        def generate(*args, **kwargs):
            events.append("call")
            return real_generate(*args, **kwargs)

        self.adapter.generate = generate
        self.adapter.sequence = ["error"]  # one loop ends its first round blocked_api
        real_external = self.external

        def external(loop, pending, iteration):
            events.append("external%d" % iteration)
            return real_external(loop, pending, iteration)

        loops = self.loops()
        for loop in loops:
            loop.external_runner = external
            loop._assemble = (lambda original: lambda target: (
                events.append("assemble"), original(target))[1])(loop._assemble)
        delays = []
        outcomes = rs.drive(loops, parallel=2, log=quiet, sleep=delays.append)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(delays, [600.0])
        self.assertEqual(events.count("call"), 9)  # 8 requests + the re-queued failed one
        first_call = events.index("call")
        last_call = len(events) - 1 - events[::-1].index("call")
        self.assertNotIn("external1", events[first_call:])
        self.assertNotIn("assemble", events[:last_call])
        self.assertNotIn("external2", events[:last_call])
        self.assertEqual(events.count("external1"), 4)
        self.assertEqual(events.count("assemble"), 4)
        for loop in loops:
            report = vs.Report(loop.model_id)
            vs.continued_loop(self.loop(loop.model_id, loop.variant), report,
                              OrderedDict([("reused", Counter()), ("new", Counter())]))
            self.assertEqual(report.status, "PASS", [c for c in report.checks if c["status"] != "PASS"])

    def test_resume_holds_loops_past_their_provider_phase(self):
        """An interrupted run left one loop past its provider phase and the
        others still before submission: the resumed drive sends every
        remaining request before it analyzes the finished loop."""
        self.step_until(lambda: self.loop(sl.MODELS[0], "static_feedback"), "requests_built", 2)
        self.loop(sl.MODELS[0], "static_feedback").step()  # its provider phase ended
        self.assertEqual(self.loop(sl.MODELS[0], "static_feedback").load_wave_state()["phase"],
                         "responses_merged")
        for model, variant in ((sl.MODELS[0], "combined_feedback"), (sl.MODELS[1], "static_feedback")):
            self.step_until(lambda: self.loop(model, variant), "requests_built", 2)
        events = []
        real_generate = self.adapter.generate

        def generate(*args, **kwargs):
            events.append("call")
            return real_generate(*args, **kwargs)

        self.adapter.generate = generate
        real_external = self.external

        def external(loop, pending, iteration):
            events.append("external%d" % iteration)
            return real_external(loop, pending, iteration)

        loops = self.loops()
        for loop in loops:
            loop.external_runner = external
            loop._assemble = (lambda original: lambda target: (
                events.append("assemble"), original(target))[1])(loop._assemble)
        outcomes = rs.drive(loops, parallel=2, log=quiet, sleep=quiet)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        last_call = len(events) - 1 - events[::-1].index("call")
        self.assertNotIn("assemble", events[:last_call])
        self.assertNotIn("external2", events[:last_call])
        self.assertEqual(events.count("call"), 6)  # 2 already answered + 6 remaining = 8
        self.assertEqual(len(self.adapter.calls), 8)

    def test_resume_with_every_loop_past_its_provider_phase_still_finishes(self):
        for model in sl.MODELS:
            for variant in sl.CONTINUE_VARIANTS:
                self.step_until(lambda: self.loop(model, variant), "requests_built", 2)
                self.loop(model, variant).step()
        calls = len(self.adapter.calls)
        outcomes = rs.drive(self.loops(), parallel=2, log=quiet, sleep=quiet)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(len(self.adapter.calls), calls)

    def test_submission_order_interleaves_models(self):
        order = [rs.key(loop) for loop in rs._interleaved(self.loops())]
        self.assertEqual(order, ["%s/static_feedback" % sl.MODELS[0], "%s/static_feedback" % sl.MODELS[1],
                                 "%s/combined_feedback" % sl.MODELS[0],
                                 "%s/combined_feedback" % sl.MODELS[1]])

    def test_failed_external_round_is_retried_once_missing_only(self):
        model = sl.MODELS[1]
        loops = [l for l in self.loops([model]) if l.variant == "combined_feedback"]
        real = self.external
        calls = []

        def flaky(loop, pending, iteration):
            calls.append((iteration, tuple(t for t, _ in pending)))
            if len(calls) == 1:
                return [tool for tool, _ in pending]  # the container failed, wrote nothing
            return real(loop, pending, iteration)

        loops[0].external_runner = flaky
        delays = []
        outcomes = rs.drive(loops, parallel=1, log=quiet, sleep=delays.append, external_retry_delay=5.0)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(delays, [5.0])
        self.assertEqual(calls[:2], [(1, ("llov",)), (1, ("llov",))])

    def test_recorded_provider_failure_is_requeued_by_the_driver(self):
        model = sl.MODELS[0]
        self.adapter.sequence = ["error"]
        delays = []
        loops = [l for l in self.loops([model]) if l.variant == "static_feedback"]
        outcomes = rs.drive(loops, parallel=1, log=quiet, sleep=delays.append, api_retry_delay=7.0)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(delays, [7.0])
        loop = self.loop(model, "static_feedback")
        self.assertEqual(sorted(loop.counted_rounds().values()), [1, 2])
        failed = loop.paths.iter_generations_path(2).with_name("failed_responses.jsonl")
        self.assertEqual(len(sw.read_jsonl(failed)), 1)  # the recorded failure stays archived
        report = vs.Report(model)
        vs.continued_loop(loop, report, OrderedDict([("reused", Counter()), ("new", Counter())]))
        self.assertEqual(report.status, "PASS", [c for c in report.checks if c["status"] != "PASS"])

    def test_refused_before_send_is_not_a_round(self):
        model = sl.MODELS[0]
        factory = lambda: self.loop(model, "combined_feedback")  # noqa: E731
        self.step_until(factory, "requests_built", 2)
        from thesis.evaluation.run_authorization import PreRunInfrastructureFailure
        StubSuccessorLoop.guard_refusal = PreRunInfrastructureFailure("guard refused")
        with self.assertRaises(PreRunInfrastructureFailure):
            factory().step()
        self.assertEqual(factory().submission_ledger(), [])  # guard runs before the intent
        StubSuccessorLoop.guard_refusal = None
        self.adapter.sequence = ["chokepoint"]
        with self.assertRaises(PreRunInfrastructureFailure):
            factory().step()
        kinds = [r["kind"] for r in factory().submission_ledger()]
        self.assertEqual(kinds, ["intent", "refused_before_send"])
        self.assertEqual(factory().counted_rounds(), {})
        self.assertEqual(set(self.drive([factory()]).values()), {orchestrator.OUTCOME_DONE})
        self.assertEqual(sorted(factory().counted_rounds().values()), [1, 1])

    def test_stop_event_blocks_new_intents(self):
        model = sl.MODELS[0]
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        self.step_until(factory, "requests_built", 2)
        sr.STOP_EVENT.set()
        with self.assertRaises(sr.StopRequested):
            factory().step()
        self.assertEqual(factory().submission_ledger(), [])
        self.assertEqual(self.adapter.calls, [])

    def test_torn_tails(self):
        model = sl.MODELS[0]
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        loop = self.step_until(factory, "decided", 1)
        requests = loop.paths.requests_path(2)
        requests.parent.mkdir(parents=True, exist_ok=True)
        requests.write_bytes(b'{"partial": ')
        factory().step()
        self.assertTrue(requests.with_name("requests.jsonl.torn").exists())
        self.assertEqual(len(factory().load_requests(2)), 2)
        with loop.paths.state_path.open("ab") as handle:
            handle.write(b'{"torn"')
        with self.assertRaises(RecoveryRefused):
            factory().step()

    def test_predecessor_drift_and_authority_refuse_before_any_write(self):
        model = sl.MODELS[0]
        loop = self.loop(model, "static_feedback")
        relative = sh.repair_dir(model, "static_feedback") + "/state.jsonl"
        path = self.world.root / relative
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        with self.assertRaises(RecoveryRefused):
            loop.step()
        path.write_bytes(original)
        self.authority.refuse = True
        with self.assertRaises(RecoveryRefused):
            loop.step()
        self.assertEqual(self.world.successor_files(),
                         [sw.LOCK_DIR + "/%s.writer.lock" % sl.SUCCESSOR])

    def test_guards(self):
        model = sl.MODELS[0]
        loop = self.loop(model, "static_feedback")
        sample = sample_id(model, "omp", 0)
        for call in (lambda: loop._run_analysis_stages(1, ["static"]),
                     lambda: loop._submit(1), lambda: loop._finish_responses(1),
                     lambda: loop._assemble(1), lambda: loop._build_requests(1),
                     lambda: loop.save_wave_state(0, "analyzed"),
                     lambda: loop.mark_unusable(sample, 0, "x"),
                     lambda: loop.append_sample_state(sample, 0, "active", "x"),
                     lambda: loop.run_external_docker([("parcoach", 1)], 1),
                     lambda: loop._load_terminal_responses(loop.paths.iter_generations_path(1))):
            with self.assertRaises(RecoveryRefused):
                call()
        with self.assertRaises(RecoveryRefused):
            StubSuccessorLoop(self.world.config, "synthetic.yaml", sl.PROFILE,
                              self.world.config["profiles"][sl.PROFILE], self.world.models[model],
                              "test_feedback", lineage=self.world.lineage,
                              parent_lineage=self.world.parent, authority=self.authority)
        command = loop.external_command("llov", 1)
        self.assertIn("--name pareval-%s-%s-static_feedback-it1-llov" % (sl.SUCCESSOR, model), command)
        self.assertIn("--label %s=%s" % (sr.CONTAINER_LABEL, sl.SUCCESSOR), command)
        self.assertIn("-e %s " % sr.TOKEN_ENV, command)
        self.assertNotIn(self.token, command)
        self.assertIn("successor_external.py", command)
        self.assertEqual(self.world.successor_files(),
                         [sw.LOCK_DIR + "/%s.writer.lock" % sl.SUCCESSOR])


class ReviewRegressionTests(SuccessorWorldCase):
    def test_operator_abort_in_a_serial_step_stops_every_loop(self):
        loops = self.loops()
        original = loops[0].step

        def interrupted():
            raise KeyboardInterrupt()

        loops[0].step = interrupted
        with self.assertRaises(KeyboardInterrupt):
            rs.drive(loops, parallel=2, log=quiet, sleep=quiet)
        self.assertTrue(sr.STOP_EVENT.is_set())
        self.assertEqual(self.adapter.calls, [])
        loops[0].step = original

    def test_duplicate_loops_are_refused(self):
        with self.assertRaises(RecoveryRefused):
            self.loops([sl.MODELS[0], sl.MODELS[0]])
        loop = self.loop(sl.MODELS[0], "static_feedback")
        with self.assertRaises(RecoveryRefused):
            rs.drive([loop, self.loop(sl.MODELS[0], "static_feedback")], log=quiet, sleep=quiet)

    def test_refusal_then_failure_then_requeue_stays_within_the_bound(self):
        model = sl.MODELS[0]
        target = sample_id(model, "mpi", 0)
        factory = lambda: self.loop(model, "static_feedback")  # noqa: E731
        self.step_until(factory, "requests_built", 2)
        self.adapter.sequence = ["chokepoint"]
        from thesis.evaluation.run_authorization import PreRunInfrastructureFailure
        with self.assertRaises(PreRunInfrastructureFailure):
            factory().step()
        self.adapter.sequence = ["error"]
        outcomes = rs.drive([factory()], parallel=1, log=quiet, sleep=quiet)
        self.assertEqual(set(outcomes.values()), {orchestrator.OUTCOME_DONE})
        loop = factory()
        self.assertEqual(loop.counted_rounds()[target], 2)
        self.assertEqual(len([r for r in loop.submission_intents() if r["sample_id"] == target]), 3)
        report = vs.Report(model)
        counts = OrderedDict([("reused", Counter()), ("new", Counter())])
        vs.continued_loop(loop, report, counts)
        self.assertEqual(report.status, "PASS", [c for c in report.checks if c["status"] != "PASS"])
        self.assertEqual(counts["new"]["iteration2_refused_before_send"], 1)

    def test_wave_state_must_be_successor_written(self):
        model = sl.MODELS[0]
        loop = self.step_until(lambda: self.loop(model, "static_feedback"), "decided", 1)
        state = json.loads(loop.paths.wave_state_path.read_text(encoding="utf-8"))
        state.pop("lineage_sha256")
        loop.paths.wave_state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(RecoveryRefused):
            self.loop(model, "static_feedback").load_wave_state()

    def test_contract_rebuild_requires_the_writer_token(self):
        from thesis.evaluation import successor_contract as sc

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

    def test_unbound_supplement_rows_refuse_in_read_only_mode(self):
        model = sl.MODELS[0]
        sx.run_supplement(self.world.root, self.world.lineage, self.world.config, model,
                          "static_feedback", "llov",
                          {"contract_sha256": "c" * 64, "authorization_sha256": "a" * 64}, {},
                          FakeLLOV(), self.world.static_settings["llov"], self.world.context,
                          self.token, log=quiet)
        loop = rs.build_loops(self.world.config, "synthetic.yaml", self.world.lineage,
                              self.world.parent, rs.NullAuthority(), models=[model])[0]
        with self.assertRaises(RecoveryRefused) as raised:
            loop.iteration1_static()
        self.assertIn("no persisted successor authorization", str(raised.exception))


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
    """successor_external.run: argument routing, writer token, targets."""

    def setUp(self):
        super().setUp()
        definitions = self.world.root / sl.DEFINITIONS_REL
        definitions.mkdir(parents=True, exist_ok=True)
        (definitions / "lineage.json").write_text(json.dumps(self.world.lineage.document),
                                                  encoding="utf-8")
        config_path = self.world.root / sl.CONFIG_REL
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(self.world.config), encoding="utf-8")
        self.previous = os.environ.get(sw.TOKEN_ENV)
        os.environ[sw.TOKEN_ENV] = self.token
        self.addCleanup(self.restore_token)
        from unittest import mock

        settings = self.world.static_settings
        patches = [
            mock.patch.object(sx, "resolve_tool", lambda config, tool: (
                FakeLLOV() if tool == "llov" else FakeParcoach(), {tool: settings[tool]},
                {n: s for n, s in settings.items() if s.enabled})),
            mock.patch.object(sx, "evaluation_context", lambda config: self.world.context),
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
                      target_run_id=sh.predecessor_iteration_run("static_feedback", 1),
                      model_id=sl.MODELS[0], variant="static_feedback", iteration=1, tool="llov")
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_supplement_mode_is_missing_only(self):
        authority = FakeContainerAuthority()
        self.assertEqual(sx.run(self.args(), root=self.world.root, authority=authority, log=quiet), 3)
        self.assertEqual(sx.run(self.args(), root=self.world.root, authority=authority, log=quiet), 0)
        self.assertEqual(authority.enforced, [("llov", sl.MODELS[0])] * 2)
        rows = sw.read_jsonl(self.world.root / ss.supplement_relative(
            sl.SUCCESSOR, sl.MODELS[0], sh.predecessor_iteration_run("static_feedback", 1), "llov"))
        self.assertEqual({r["stage_runtime_sha256"] for r in rows}, {"s" * 64})

    def test_refusals_before_any_write(self):
        authority = FakeContainerAuthority()
        refused = [
            self.args(tool="parcoach"),                           # stored entries never re-run
            self.args(target_run_id=sh.predecessor_iteration_run("static_feedback", 2)),
            self.args(iteration=2, target_run_id="%s__static_feedback__iter2" % sl.SUCCESSOR),
            self.args(variant="test_feedback",
                      target_run_id=sh.predecessor_iteration_run("test_feedback", 1)),
            self.args(model_id="openai_gpt55"),
            self.args(run_id=sl.PREDECESSOR),
        ]
        for args in refused:
            with self.assertRaises(RecoveryRefused):
                sx.run(args, root=self.world.root, authority=authority, log=quiet)
        os.environ[sw.TOKEN_ENV] = "0" * 32
        with self.assertRaises(RecoveryRefused):
            sx.run(self.args(), root=self.world.root, authority=authority, log=quiet)
        self.assertEqual(authority.enforced, [])
        self.assertEqual(self.world.successor_files(),
                         [sw.LOCK_DIR + "/%s.writer.lock" % sl.SUCCESSOR])


class SupplementTests(SuccessorWorldCase):
    def supplement(self, model, variant, tool="llov", token=None):
        return sx.run_supplement(self.world.root, self.world.lineage, self.world.config, model, variant,
                                 tool, {"contract_sha256": "c" * 64, "authorization_sha256": "a" * 64},
                                 {}, FakeLLOV(), self.world.static_settings[tool], self.world.context,
                                 token or self.token, log=quiet)

    def test_missing_only_and_idempotent(self):
        model = sl.MODELS[0]
        self.assertEqual(self.supplement(model, "static_feedback"), 3)
        self.assertEqual(self.supplement(model, "static_feedback"), 0)
        with self.assertRaises(RecoveryRefused):
            self.supplement(model, "combined_feedback", token="f" * 32)
        with self.assertRaises(RecoveryRefused):
            self.supplement(model, "static_feedback", tool="parcoach")  # stored entries never re-run

    def test_entry_equals_native_run_model(self):
        """The supplement entry is byte-identical to the entry
        run_static_analysis.run_model writes for the same tool/sample."""
        model = sl.MODELS[1]
        self.supplement(model, "static_feedback")
        loop = self.loop(model, "static_feedback")
        rows = {r["sample_id"]: r for r in loop.supplement_rows("llov")}
        run = sh.predecessor_iteration_run("static_feedback", 1)
        with tempfile.TemporaryDirectory() as other:
            intermediate = Path(other)
            target = intermediate / run / model
            target.mkdir(parents=True)
            source_rel = sh.iteration_dir(run, model) + "/assembly.jsonl"
            (target / "assembly.jsonl").write_bytes(self.world.lineage.view.read_bytes(source_rel))
            previous = framework._TOOL_REGISTRY.get("llov")
            framework.register_tool(FakeLLOV())
            try:
                rsa.run_model(context=self.world.context, intermediate_dir=intermediate, run_id=run,
                              model_id=model, tool_settings={"llov": self.world.static_settings["llov"]},
                              invocation_label="equivalence")
            finally:
                if previous is not None:
                    framework.register_tool(previous)
                else:
                    framework._TOOL_REGISTRY.pop("llov", None)
            native = {}
            for line in (target / "static_analysis.jsonl").read_text(encoding="utf-8").split("\n"):
                if line.strip():
                    record = json.loads(line)
                    native[record["sample_id"]] = record["tools"]["llov"]
        self.assertEqual(set(native), set(rows))
        for sample, entry in native.items():
            self.assertEqual(json.dumps(rows[sample]["entry"], sort_keys=True),
                             json.dumps(entry, sort_keys=True), sample)

    def test_merged_view_never_replaces_stored_entries(self):
        record = {"s": {"tools": {"llov": {"tool": "llov", "analysis_state": "TIMEOUT"}}}}
        with self.assertRaises(RecoveryRefused):
            ss.merge_static_records(record, {"llov": {"s": {"tool": "llov"}}})
        with self.assertRaises(RecoveryRefused):
            ss.merge_static_records({}, {"llov": {"s": {"tool": "llov"}}})

    def test_supplement_bound_to_authority(self):
        model = sl.MODELS[0]
        self.supplement(model, "static_feedback")
        loop = self.loop(model, "static_feedback")
        self.assertEqual(len(loop.iteration1_static()), 3)
        self.authority.contract_sha256 = "d" * 64
        try:
            with self.assertRaises(RecoveryRefused):
                loop.iteration1_static()
        finally:
            self.authority.contract_sha256 = FakeAuthority.contract_sha256


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

    def test_lock_path_is_not_version_controlled(self):
        relative = sw.lock_path(".", sl.SUCCESSOR).as_posix().lstrip("./")
        result = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(REPO_ROOT),
                                 "check-ignore", "-q", relative], capture_output=True)
        if result.returncode == 128:
            self.skipTest("git unavailable")
        self.assertEqual(result.returncode, 0, relative)


class StaticSourceTests(unittest.TestCase):
    MODULES = ("thesis/repair/successor_routing.py", "thesis/repair/run_successor.py",
               "thesis/evaluation/successor_external.py", "thesis/evaluation/successor_contract.py",
               "thesis/evaluation/successor_lineage.py", "thesis/evaluation/successor_handoff.py",
               "thesis/evaluation/successor_supplement.py", "thesis/evaluation/successor_writer.py",
               "thesis/evaluation/successor_equivalence.py", "thesis/evaluation/verify_successor_run.py")

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
            self.assertFalse([n for n in names if "recovery_contract" in n or n == "run_repair"],
                             relative)

    def test_contract_dispatch_is_the_only_pinned_edit(self):
        from thesis.evaluation import successor_equivalence as se

        self.assertEqual(list(se.ROUTING_CHANGES), ["thesis/evaluation/pilot_run_contract.py"])
        text = (REPO_ROOT / "thesis/evaluation/pilot_run_contract.py").read_text(encoding="utf-8")
        self.assertIn('if profile_name == "recovery_successor":', text)


if __name__ == "__main__":
    unittest.main()
