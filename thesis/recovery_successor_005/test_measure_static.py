"""Tests of the phase-2 static backfill (measure_static + external).

A synthetic repository in a temp dir holds ONE test_feedback target (its
assembly, candidate sources and a historical static_analysis.jsonl that
carries only the compiler entry) plus a static_feedback target that is never
read. Stub tools are registered under the real tool names (subclasses of the
real tool classes with their real constructor options; the registry is
restored afterwards), so the measurement path is the native one end to end:
successor_supplement.measure_entry -> tool_execution_condition -> tool.run.
Nothing touches thesis/results of the real repository; no compiler runs.

    python3 -B -m unittest -v thesis.recovery_successor_005.test_measure_static
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import hashlib
import importlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest import mock

from thesis.evaluation import effective_invocation, framework, stage_runtime
from thesis.evaluation import run_static_analysis as rsa
from thesis.evaluation import static_provenance as provenance
from thesis.evaluation import successor_writer as sw
from thesis.evaluation import tools as tool_module
from thesis.evaluation.condition_hashing import canonical_sha256, utf8_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.recovery_successor_005 import external as ex
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import measure_static as ms
from thesis.recovery_successor_005 import plan as pp
from thesis.recovery_successor_005 import targets as pt

REPO_ROOT = Path(__file__).resolve().parents[2]
LOAD_CONFIG = importlib.import_module("thesis.config.load_config")
CONFIG_TEMPLATE = json.loads((REPO_ROOT / pl.CONFIG_REL).read_text(encoding="utf-8"),
                             object_pairs_hook=OrderedDict)
MODEL = "claude_fable_5"
SOURCE_RUN = "full_ext_recovery_001__test_feedback__iter1"
STATIC_RUN = "full_ext_recovery_003__static_feedback__iter2"  # in the table, never read here
SAMPLES = (("sort", "radix", "serial"), ("sort", "radix", "omp"),
           ("reduce", "sum", "mpi"), ("reduce", "sum", "omp"))
MAIN_TOOLS = ["gcc_analyzer", "clang_tidy", "cppcheck", "infer"]
ALL_MISSING = MAIN_TOOLS + ["parcoach", "llov"]
TORN = b'{"schema_version": "successor_static_supplement.v1", "run_id": "full_ext_ph'

CALLS = []          # (tool, sample_id) of every stub tool run
HOOKS = {}          # tool -> callable(sample) run inside the stub (drift / crash simulation)
UNAVAILABLE = set()  # tools whose stub reports is_available() False
REGISTRATIONS = []  # (primary_compiler, config) of every register_default_tools call
REAL_REGISTER = tool_module.register_default_tools


class SimulatedCrash(BaseException):
    """Like KeyboardInterrupt / SystemExit: nothing catches it."""


def sample_id(index):
    problem, name, model = SAMPLES[index]
    return "%s__%s__%s__%s__sample_0" % (MODEL, problem, name, model)


def stub_identity(name):
    return "stub-%s 1.0" % name


def stub_result(name, sample):
    """Deterministic per (tool, candidate bytes); no path in the output, so
    the same candidate gives the same entry in any checkout."""
    digest = hashlib.sha256(sample.source_path.read_bytes()).hexdigest()[:12]
    model = sample.execution_model
    findings = []
    if name == "gcc_analyzer" and model != "serial":
        findings.append(framework.Finding(name, "-Wanalyzer-null-dereference", "warning",
                                          "dereference of NULL (%s)" % digest, "generated-code.hpp", 3, 5, True))
    if name == "clang_tidy":
        findings.append(framework.Finding(name, "clang-analyzer-optin.mpi.MPI-Checker", "warning",
                                          "request %s" % digest, "generated-code.hpp", 2, 1, False))
    if name == "cppcheck" and model == "omp":
        findings.append(framework.Finding(name, "uninitvar", "error", "uninitialized (%s)" % digest,
                                          "generated-code.hpp", 4, 9, True))
    if name == "parcoach":
        findings.append(framework.Finding(name, "parcoach-collective-mismatch", "warning",
                                          "collective (%s)" % digest, "generated-code.hpp", 6, 1, True))
    if name == "llov":
        findings.append(framework.Finding(name, "llov-data-race", "error", "race (%s)" % digest,
                                          "generated-code.hpp", 5, 1, True))
    return framework.ToolResult(tool=name, ran=True, exit_code=0, duration_seconds=0.25, findings=findings,
                                raw_stdout="%s analysed %s (%s)" % (name, sample.sample_id, digest),
                                analysis_state=framework.STATE_COMPLETED,
                                analysis_details={"stub": True, "source": digest})


def stub_class(base):
    class Stub(base):
        available = True

        def is_available(self):
            return self.available

        def run(self, sample, context):
            CALLS.append((self.name, sample.sample_id))
            hook = HOOKS.get(self.name)
            if hook is not None:
                hook(sample)
            return stub_result(self.name, sample)

    Stub.__name__ = "Stub" + base.__name__
    return Stub


def register_stubs(primary_compiler="g++", config=None):
    """register_default_tools, then every real tool object becomes a stub of
    its own class with its own (config-resolved) options."""
    REGISTRATIONS.append((primary_compiler, config))
    REAL_REGISTER(primary_compiler=primary_compiler, config=config)
    for name in list(framework._TOOL_REGISTRY):
        real = framework._TOOL_REGISTRY[name]
        cls = stub_class(type(real))
        stub = cls.__new__(cls)
        stub.__dict__.update(real.__dict__)
        stub.available = name not in UNAVAILABLE
        framework._TOOL_REGISTRY[name] = stub


def entry_of(name, **fields):
    entry = framework.ToolResult(tool=name, ran=True, exit_code=fields.pop("exit_code", 0),
                                 duration_seconds=fields.pop("duration", 1.5), **fields).to_dict()
    entry["num_low_confidence"] = 0
    entry["tool_execution_fingerprint_sha256"] = "f" * 64
    entry["tool_execution_condition"] = OrderedDict([("tool", name), ("historical", True)])
    return entry


def test_config(root):
    config = copy.deepcopy(CONFIG_TEMPLATE)
    config["outputs"] = OrderedDict(config["outputs"],
                                    raw_dir=(root / "thesis/results/raw").as_posix(),
                                    intermediate_dir=(root / "thesis/results/intermediate").as_posix(),
                                    processed_dir=(root / "thesis/results/processed").as_posix())
    return config


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
    path.write_bytes(data)
    return data


class World:
    """One test_feedback target (4 candidates) whose historical static record
    holds the compiler entry (+ optional extra historical entries)."""

    def __init__(self, root, extra=None):
        self.root = root
        self.config = test_config(root)
        base = pt.run_dir(SOURCE_RUN, MODEL)
        assembly, facts, records = [], [], []
        for index, (problem, name, model) in enumerate(SAMPLES):
            sid = sample_id(index)
            relative = "%s/sources/%s/generated-code.hpp" % (base, sid)
            source = ("// candidate %s\nint kernel(int n) { return n * %d; }\n" % (sid, index + 2)).encode()
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_bytes(source)
            sha = hashlib.sha256(source).hexdigest()
            assembly.append(OrderedDict([
                ("run_id", SOURCE_RUN), ("model_id", MODEL), ("sample_id", sid), ("assembled", True),
                ("source_path", relative), ("source_sha256", sha), ("execution_model", model),
                ("benchmark", "%s/%s" % (problem, name)),
                ("drivers", OrderedDict([("benchmark_dir", "drivers/cpp/benchmarks/%s/%s" % (problem, name)),
                                         ("model_driver", "drivers/cpp/models/%s-driver.cc" % model)]))]))
            facts.append(OrderedDict([("sample_id", sid), ("execution_model", model),
                                      ("benchmark", "%s/%s" % (problem, name)),
                                      ("source_sha256", sha), ("source_path", relative)]))
            tools = OrderedDict([("compiler", entry_of("compiler", analysis_state=framework.STATE_COMPLETED,
                                                       analysis_details={"build_ok": True}))])
            tools.update((extra or {}).get(index) or {})
            record = OrderedDict([("schema_version", rsa.STATIC_ANALYSIS_SCHEMA_VERSION), ("run_id", SOURCE_RUN),
                                  ("model_id", MODEL), ("sample_id", sid), ("execution_model", model),
                                  ("tools", tools), ("sample_source_sha256", sha),
                                  ("created_at_utc", "2026-09-01T00:00:00Z"),
                                  ("tool_state_schema", framework.TOOL_STATE_SCHEMA_VERSION)])
            record["has_blocking_findings"] = rsa.record_has_blocking(record)
            record["low_confidence_count"] = rsa.record_low_confidence_count(record)
            record["analysis_gaps"] = rsa.record_analysis_gaps(record)
            records.append(record)
        data = write_jsonl(root / base / "assembly.jsonl", assembly)
        write_jsonl(root / base / pt.STATIC_FILE, records)
        (root / "drivers/cpp").mkdir(parents=True, exist_ok=True)
        document = OrderedDict([
            ("target_id", "%s/%s" % (MODEL, SOURCE_RUN)), ("model_id", MODEL), ("block", "full_ext"),
            ("variant", "test_feedback"), ("iteration", 1), ("source_run", SOURCE_RUN),
            ("loop_owner", "full_ext_recovery_001"), ("loop_kind", "native"),
            ("assembly", OrderedDict([("path", base + "/assembly.jsonl"),
                                      ("raw_sha256", hashlib.sha256(data).hexdigest())])),
            ("sample_count", len(facts)), ("samples", facts)])
        static_document = OrderedDict(copy.deepcopy(document), target_id="%s/%s" % (MODEL, STATIC_RUN),
                                      variant="static_feedback", iteration=2, source_run=STATIC_RUN,
                                      loop_owner="full_ext_recovery_003", loop_kind="continued")
        table = OrderedDict([
            ("schema_version", pt.SCHEMA), ("run_id", pl.SUCCESSOR), ("model_ids", list(pl.MODELS)),
            ("excluded_historical_runs", list(pl.EXCLUDED_HISTORICAL_RUNS)), ("census_digest", "0" * 64),
            ("census_summary", OrderedDict()), ("target_count", 2),
            ("sample_totals", OrderedDict([("static_feedback", 4), ("test_feedback", 4)])),
            ("targets", [document, static_document])])
        table["table_sha256"] = canonical_sha256(table)
        definitions = root / pl.DEFINITIONS_REL
        definitions.mkdir(parents=True, exist_ok=True)
        (definitions / "targets.json").write_text(json.dumps(table, indent=1), encoding="utf-8")
        (root / pl.CONFIG_REL).parent.mkdir(parents=True, exist_ok=True)
        (root / pl.CONFIG_REL).write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        self.table = pt.load_table(root, table["table_sha256"])
        self.target = self.table.get(document["target_id"])
        self.static_target = self.table.get(static_document["target_id"])

    def source(self, index):
        return self.root / self.target.samples[sample_id(index)]["source_path"]


def binding_sha(*parts):
    return hashlib.sha256("/".join(parts).encode("utf-8")).hexdigest()


class FakeAuthority:
    """The lead's run.py authority interface."""

    def __init__(self, token):
        self.token = token
        self.checks = 0
        self.enforced = []

    def check(self):
        self.checks += 1

    def enforce(self, stage, model):
        self.enforced.append((stage, model))
        return dict(self.binding(stage, model))

    def binding(self, stage, model):
        return OrderedDict([("contract_sha256", "c" * 64), ("authorization_sha256", "a" * 64),
                            ("stage_runtime_sha256", binding_sha("runtime", stage, model)),
                            ("invocation_sha256", binding_sha("invocation", stage, model))])


class FakeContainerAuthority:
    def __init__(self, targets_sha256, refuse=None, drift=False):
        self.targets_sha256 = targets_sha256
        self.refuse = refuse
        self.drift = drift
        self.enforced = []

    def validate(self):
        if self.refuse:
            raise RecoveryRefused(self.refuse)
        return OrderedDict([("contract_sha256", "c" * 64), ("authorization_sha256", "a" * 64),
                            ("targets_sha256", self.targets_sha256)])

    def enforce(self, tool, model):
        if self.drift:
            raise stage_runtime.StageRuntimeDrift("static.%s" % tool, tool, "pinned", "moved", ["image_id"])
        self.enforced.append((tool, model))
        return {"enforced": True, "stage_runtime_sha256": binding_sha("runtime", tool, model),
                "invocation_sha256": binding_sha("invocation", tool, model)}


class InProcessContainer:
    """subprocess.run replacement: executes the container command's module
    in-process (external.main, fake container authority) as the pinned image
    would - with the token taken from the passed environment ONLY."""

    def __init__(self, case, authority=None):
        self.case = case
        self.authority = authority or FakeContainerAuthority(case.world.table.sha256)
        self.commands, self.environments, self.kills, self.codes = [], [], [], []

    def __call__(self, command, **kwargs):
        if isinstance(command, list):
            self.kills.append(command)
            return subprocess.CompletedProcess(command, 0)
        self.commands.append(command)
        environment = kwargs["env"]
        self.environments.append(environment)
        tokens = shlex.split(command)
        module = tokens.index("-m")
        if tokens[module + 1] != ms.EXTERNAL_MODULE or not kwargs.get("shell"):
            raise AssertionError("unexpected container command: %s" % command)
        factory = lambda config, config_path, root: self.authority  # noqa: E731
        with mock.patch.dict(os.environ, {sw.TOKEN_ENV: environment[sw.TOKEN_ENV]}), \
                mock.patch.object(ex, "REPO_ROOT", self.case.root), \
                mock.patch.object(ex, "ContainerAuthority", factory), \
                mock.patch.object(LOAD_CONFIG, "load_dotenv", lambda *a, **k: None), \
                contextlib.redirect_stdout(io.StringIO()):
            code = ex.main(tokens[module + 2:])
        self.codes.append(code)
        return subprocess.CompletedProcess(command, code)


def schema_003():
    """[(key, nested keys or None)] of the row literal in
    recovery_successor_003/external.py::run_supplement (read by AST)."""
    tree = ast.parse((REPO_ROOT / "thesis/recovery_successor_003/external.py").read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "run_supplement")
    call = next(node for node in ast.walk(function)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "durable_append_jsonl")

    def keys(node):
        result = []
        for element in node.args[0].elts:
            key, value = element.elts
            nested = None
            if isinstance(value, ast.Call) and getattr(value.func, "id", None) == "OrderedDict":
                nested = [k for k, _ in keys(value)]
            result.append((key.value, nested))
        return result

    return keys(call.args[1])


class Phase2StaticCase(unittest.TestCase):
    extra = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.world = World(self.root, self.extra)
        saved = dict(framework._TOOL_REGISTRY)

        def restore():
            framework._TOOL_REGISTRY.clear()
            framework._TOOL_REGISTRY.update(saved)

        self.addCleanup(restore)
        for patch in (mock.patch.object(tool_module, "register_default_tools", register_stubs),
                      mock.patch.object(tool_module, "tool_runtime_identity", stub_identity)):
            patch.start()
            self.addCleanup(patch.stop)
        del CALLS[:]
        del REGISTRATIONS[:]
        HOOKS.clear()
        UNAVAILABLE.clear()
        self.token = sw.WriterLock(self.root, pl.SUCCESSOR, "test").acquire()
        self.authority = FakeAuthority(self.token)
        self.logs = []
        # the tool containers mount the HOST repository (no silent fallback)
        environment = mock.patch.dict(os.environ, {"PAREVAL_HOST_REPO": "/host/repo"})
        environment.start()
        self.addCleanup(environment.stop)

    def run_main(self, targets=None, **kwargs):
        return ms.run_main(self.root, self.world.config, self.world.table, self.authority,
                           targets if targets is not None else [self.world.target], log=self.logs.append,
                           **kwargs)

    def ledger(self, tool):
        return sw.read_jsonl(self.root / pt.ledger_relative(MODEL, SOURCE_RUN, "static.%s.jsonl" % tool))

    def phase2_files(self):
        base = self.root / pl.RESULTS_REL
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file()) \
            if base.exists() else []

    def applicable(self, tools):
        settings = pg.static_settings(self.world.config)
        return {(tool, sample_id(i)) for i in range(len(SAMPLES)) for tool in tools
                if settings[tool].applies_to(SAMPLES[i][2])}


class MainToolTests(Phase2StaticCase):
    def test_rows_are_exactly_the_missing_pairs_with_the_003_schema(self):
        counts = self.run_main()
        self.assertEqual(counts["rows"], 16)
        self.assertEqual(counts["not_applicable"], 2)  # infer is out of scope for the two omp samples
        self.assertEqual(REGISTRATIONS, [("g++", self.world.config)])
        self.assertEqual(self.authority.enforced, [("static.main", MODEL)])
        self.assertEqual(self.authority.checks, 1)
        self.assertEqual(len(CALLS), len(set(CALLS)))
        self.assertEqual(set(CALLS), self.applicable(MAIN_TOOLS))
        schema = schema_003()
        facts = self.world.target.samples
        static_rel = pt.run_dir(SOURCE_RUN, MODEL) + "/" + pt.STATIC_FILE
        static_sha = hashlib.sha256((self.root / static_rel).read_bytes()).hexdigest()
        for tool in MAIN_TOOLS:
            rows = self.ledger(tool)
            self.assertEqual([r["sample_id"] for r in rows], [sample_id(i) for i in range(len(SAMPLES))])
            for row in rows:
                self.assertEqual(list(row), [key for key, _ in schema])
                for key, nested in schema:
                    if nested is not None:
                        self.assertEqual(list(row[key]), nested, key)
                sid = row["sample_id"]
                self.assertEqual((row["schema_version"], row["run_id"], row["authority_run_id"]),
                                 ("successor_static_supplement.v1", pl.SUCCESSOR, pl.SUCCESSOR))
                self.assertEqual((row["candidate_source_run"], row["model_id"], row["variant"], row["iteration"],
                                  row["tool"], row["execution_model"]),
                                 (SOURCE_RUN, MODEL, "test_feedback", 1, tool, facts[sid]["execution_model"]))
                self.assertEqual(row["candidate_source_sha256"], facts[sid]["source_sha256"])
                self.assertEqual(row["predecessor_static_artifact"], {"path": static_rel, "raw_sha256": static_sha})
                self.assertEqual(row["predecessor_assembly_artifact"], dict(self.world.target.document["assembly"]))
                self.assertEqual(row["runner"]["template_sha256"], None)
                self.assertEqual(row["runner"]["argv"], list(sys.argv))
                self.assertEqual(OrderedDict((k, row[k]) for k in ex.BINDING_FIELDS),
                                 self.authority.binding("static.main", MODEL))
                applicable = pg.static_settings(self.world.config)[tool].applies_to(row["execution_model"])
                self.assertEqual(row["entry"]["analysis_state"],
                                 "COMPLETED" if applicable else "NOT_APPLICABLE")
                if not applicable:
                    self.assertEqual(row["entry"], rsa.not_applicable_entry(tool, row["execution_model"]))
        self.assertFalse(self.ledger("parcoach") or self.ledger("llov"))
        missing = pg.missing_static(self.root, self.world.config, self.world.target)
        self.assertEqual(missing, OrderedDict((sample_id(i), ["parcoach", "llov"]) for i in range(len(SAMPLES))))
        # a second invocation finds nothing missing: no tool run, no row
        self.assertEqual(self.run_main()["rows"], 0)
        self.assertEqual(len(CALLS), 14)

    def test_entries_equal_native_run_model(self):
        """Every supplement entry (main tools in-process, PARCOACH/LLOV via the
        container entrypoint) equals the entry run_static_analysis.run_model
        writes for the same candidate with the same tools, and the merged view
        equals the native record (derived fields included)."""
        with tempfile.TemporaryDirectory() as other:
            copy_root = Path(other).resolve() / "repo"
            shutil.copytree(str(self.root), str(copy_root))
            self.run_main()
            for tool in pl.EXTERNAL_TOOLS:
                ms.run_external(self.root, self.world.config, self.authority, self.world.target, tool,
                                log=self.logs.append, runner=InProcessContainer(self))
            settings = pg.static_settings(self.world.config)
            context = framework.EvaluationContext(repo_root=copy_root, drivers_cpp_dir=copy_root / "drivers/cpp",
                                                  primary_compiler="g++", config=self.world.config)
            register_stubs(config=self.world.config)
            with contextlib.redirect_stdout(io.StringIO()):
                rsa.run_model(context=context, intermediate_dir=copy_root / "thesis/results/intermediate",
                              run_id=SOURCE_RUN, model_id=MODEL,
                              tool_settings=OrderedDict((t, settings[t]) for t in ALL_MISSING),
                              expected_tools=settings, invocation_label="phase-2 equivalence")
            native = OrderedDict()
            for line in (copy_root / pt.run_dir(SOURCE_RUN, MODEL) / pt.STATIC_FILE).read_text(
                    encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    native[record["sample_id"]] = record
        pairs = set()
        for tool in ALL_MISSING:
            for row in self.ledger(tool):
                pairs.add((tool, row["sample_id"]))
                self.assertEqual(json.dumps(row["entry"], sort_keys=True),
                                 json.dumps(native[row["sample_id"]]["tools"][tool], sort_keys=True),
                                 (tool, row["sample_id"]))
        self.assertEqual(pairs, {(t, sample_id(i)) for t in ALL_MISSING for i in range(len(SAMPLES))})
        merged = pg.merged_static(self.root, self.world.config, self.world.target)
        for sid, record in native.items():
            self.assertEqual(json.dumps(merged[sid]["tools"], sort_keys=True),
                             json.dumps(record["tools"], sort_keys=True))
            for field in ("has_blocking_findings", "low_confidence_count", "analysis_gaps"):
                self.assertEqual(merged[sid][field], record[field], (sid, field))
        # the measured state is not trivial: findings, blocking and low-confidence marks
        self.assertTrue(any(r["has_blocking_findings"] for r in native.values()))
        self.assertTrue(all(r["low_confidence_count"] >= 1 for r in native.values()))

    def test_resume_after_crash_and_torn_tail_writes_exactly_the_missing_rows(self):
        crashing = sample_id(1)

        def crash(sample):
            if sample.sample_id == crashing:
                raise SimulatedCrash("killed during clang_tidy")

        HOOKS["clang_tidy"] = crash
        with self.assertRaises(SimulatedCrash):
            self.run_main()
        self.assertEqual({t: len(self.ledger(t)) for t in MAIN_TOOLS},
                         {"gcc_analyzer": 2, "clang_tidy": 1, "cppcheck": 1, "infer": 1})
        clang = self.root / pt.ledger_relative(MODEL, SOURCE_RUN, "static.clang_tidy.jsonl")
        with clang.open("ab") as handle:
            handle.write(TORN)
        with self.assertRaises(pg.TornLedger):
            pg.missing_static(self.root, self.world.config, self.world.target)
        HOOKS.clear()
        first_run = list(CALLS)
        counts = self.run_main()
        self.assertTrue(any("archived a torn tail" in line for line in self.logs))
        audit = clang.with_name(clang.name + ".torn")
        self.assertIn(TORN.decode("utf-8"), json.loads(audit.read_text(encoding="utf-8").splitlines()[0])["text"])
        self.assertEqual(counts["rows"], 11)
        resumed = CALLS[len(first_run):]
        self.assertFalse(set(resumed) & set(first_run[:-1]))  # nothing durable was measured again
        for tool in MAIN_TOOLS:
            ids = [r["sample_id"] for r in self.ledger(tool)]
            self.assertEqual(sorted(ids), sorted(sample_id(i) for i in range(len(SAMPLES))), tool)
        self.assertEqual(set(CALLS), self.applicable(MAIN_TOOLS))
        self.assertEqual(pg.missing_static(self.root, self.world.config, self.world.target),
                         OrderedDict((sample_id(i), ["parcoach", "llov"]) for i in range(len(SAMPLES))))

    def test_stop_is_honoured_between_samples(self):
        counts = self.run_main(stop=lambda: len(CALLS) > 0)
        self.assertEqual((counts["rows"], counts["samples"], counts["stopped"]), (4, 1, 1))
        self.assertEqual({t: len(self.ledger(t)) for t in MAIN_TOOLS}, dict.fromkeys(MAIN_TOOLS, 1))
        self.assertEqual(self.run_main(stop=lambda: True)["rows"], 0)  # requested before the target
        self.assertEqual(self.run_main()["rows"], 12)

    def test_tool_crash_is_a_target_failure(self):
        def broken(sample):
            raise ValueError("tool wrapper bug")

        HOOKS["cppcheck"] = broken
        open_items = []
        counts = self.run_main(open_items=open_items)  # confined: recorded, the stage continues
        self.assertEqual((counts["target_failures"], open_items),
                         (1, ["static.main %s" % self.world.target.target_id]))
        self.assertEqual([len(self.ledger(t)) for t in MAIN_TOOLS], [1, 1, 0, 0])

    def test_source_drift_between_table_and_bytes_refuses(self):
        self.world.source(1).write_bytes(b"// edited after the table was frozen\n")
        with self.assertRaises(pl.GlobalStop):
            self.run_main()
        self.assertEqual(self.phase2_files(), [])
        self.assertEqual(CALLS, [])

    def test_source_drift_while_the_tool_runs_refuses_that_row(self):
        def edit(sample):
            Path(sample.source_path).write_bytes(b"// rewritten while cppcheck ran\n")

        HOOKS["cppcheck"] = edit
        with self.assertRaises(pl.GlobalStop) as raised:
            self.run_main()
        self.assertIn("drifted", str(raised.exception))
        self.assertEqual([len(self.ledger(t)) for t in MAIN_TOOLS], [1, 1, 0, 0])

    def test_wrong_token_refuses_before_any_write(self):
        self.authority.token = "0" * 32
        with self.assertRaises(pl.GlobalStop):
            self.run_main()
        self.assertEqual((self.phase2_files(), CALLS, self.authority.enforced), ([], [], []))

    def test_environment_gate_before_any_record(self):
        UNAVAILABLE.add("infer")
        with self.assertRaises(EnvironmentError) as raised:
            self.run_main()
        self.assertIn("infer", str(raised.exception))
        self.assertEqual((self.phase2_files(), CALLS, self.authority.enforced), ([], [], []))

    def test_foreign_targets_refuse_and_other_variants_are_skipped(self):
        foreign = pt.Target(OrderedDict(self.world.target.document, sample_count=99))
        with self.assertRaises(pl.GlobalStop):
            self.run_main([foreign])
        with self.assertRaises(pl.GlobalStop):
            self.run_main(["%s/full_ext_recovery_009__test_feedback__iter1" % MODEL])
        counts = self.run_main([self.world.static_target])  # its files do not even exist
        self.assertEqual((counts["skipped_targets"], counts["rows"]), (1, 0))
        self.assertEqual(self.run_main([self.world.target.target_id])["rows"], 16)


class PresentEntryTests(Phase2StaticCase):
    """Historical gaps are measurements: never re-measured."""

    extra = {
        0: {"gcc_analyzer": entry_of("gcc_analyzer", exit_code=-1, duration=300.0, error="timed out after 300 s",
                                     analysis_state=framework.STATE_TIMEOUT, analysis_gap_reason="timeout")},
        2: {"clang_tidy": entry_of("clang_tidy", exit_code=1, error="clang-tidy crashed",
                                   analysis_state=framework.STATE_TOOL_ERROR, analysis_gap_reason="crash"),
            "infer": entry_of("infer", analysis_state=framework.STATE_COMPLETED)},
    }

    def test_timeout_and_tool_error_entries_are_never_remeasured(self):
        historical = pt.historical_static(self.root, self.world.target)
        counts = self.run_main()
        self.assertEqual(counts["rows"], 13)
        never = {("gcc_analyzer", sample_id(0)), ("clang_tidy", sample_id(2)), ("infer", sample_id(2))}
        self.assertFalse(set(CALLS) & never)
        for tool, sid in never:
            self.assertNotIn(sid, [r["sample_id"] for r in self.ledger(tool)])
        merged = pg.merged_static(self.root, self.world.config, self.world.target)
        self.assertEqual(merged[sample_id(0)]["tools"]["gcc_analyzer"],
                         historical[sample_id(0)]["tools"]["gcc_analyzer"])
        self.assertEqual(merged[sample_id(2)]["tools"]["clang_tidy"]["analysis_state"], "TOOL_ERROR")
        self.assertEqual(self.run_main()["rows"], 0)

    def test_an_unavailable_tool_with_only_inapplicable_work_passes_the_gate(self):
        extra = copy.deepcopy(self.extra)
        extra[0]["infer"] = entry_of("infer", analysis_state=framework.STATE_COMPLETED)
        self.world = World(self.root, extra)  # infer present for serial + mpi: only omp (N/A) is missing
        UNAVAILABLE.add("infer")
        self.run_main()
        rows = self.ledger("infer")
        self.assertEqual([r["sample_id"] for r in rows], [sample_id(1), sample_id(3)])
        self.assertEqual({r["entry"]["analysis_state"] for r in rows}, {"NOT_APPLICABLE"})


class ExternalTests(Phase2StaticCase):
    def args(self, **overrides):
        values = dict(config=pl.CONFIG_REL, profile=pl.PROFILE, run_id=pl.SUCCESSOR,
                      target_id=self.world.target.target_id, tool="parcoach")
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_external_command_structure(self):
        with mock.patch.dict(os.environ, {"PAREVAL_HOST_REPO": "/host/repo"}):
            commands = {tool: ms.external_command(self.root, self.world.config, self.world.target, tool)
                        for tool in pl.EXTERNAL_TOOLS}
        for tool, (image, interpreter) in (("parcoach", ("registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1",
                                                         "python3")), ("llov", ("pareval-llov", "python3.8"))):
            command = commands[tool]
            self.assertNotIn(self.token, command)
            tokens = shlex.split(command)
            self.assertEqual(tokens[:2], ["docker", "run"])
            self.assertEqual(tokens[tokens.index("-v") + 1], "/host/repo:/workspace")
            self.assertEqual(tokens[tokens.index("--name") + 1],
                             "pareval-full_ext_phase2_001-%s-%s-%s" % (MODEL, SOURCE_RUN, tool))
            self.assertEqual(tokens[tokens.index("--label") + 1], "pareval.successor_run=full_ext_phase2_001")
            self.assertEqual(tokens[tokens.index("-e") + 1], "PAREVAL_SUCCESSOR_TOKEN")
            at = tokens.index(image)
            self.assertEqual(tokens[at + 1:at + 5], [interpreter, "-B", "-m", "thesis.recovery_successor_005.external"])
            tail = tokens[at + 5:]
            self.assertEqual(tail, ["--config", pl.CONFIG_REL, "--profile", pl.PROFILE, "--run-id", pl.SUCCESSOR,
                                    "--target-id", self.world.target.target_id, "--tool", tool])
            parsed = ex.parse_args(tail)
            self.assertEqual((parsed.target_id, parsed.tool), (self.world.target.target_id, tool))
        broken = copy.deepcopy(self.world.config)
        broken["stages"]["repair"]["external_tool_commands"]["llov"] = "python3.8 run_static_analysis.py"
        with self.assertRaises(RecoveryRefused):
            ms.external_command(self.root, broken, self.world.target, "llov")

    def test_container_rows_complete_the_target(self):
        self.run_main()
        runner = InProcessContainer(self)
        self.assertEqual(ms.run_external(self.root, self.world.config, self.authority, self.world.target,
                                         "parcoach", log=self.logs.append, runner=runner), 4)
        self.assertEqual(ms.run_external(self.root, self.world.config, self.authority, self.world.target,
                                         "llov", log=self.logs.append, runner=runner), 4)
        self.assertEqual(runner.codes, [0, 0])
        self.assertEqual(runner.authority.enforced, [("parcoach", MODEL), ("llov", MODEL)])
        for command, environment in zip(runner.commands, runner.environments):
            self.assertNotIn(self.token, command)
            self.assertEqual(environment[sw.TOKEN_ENV], self.token)
        self.assertEqual(self.authority.checks, 1 + 2 * 2)  # before each target, around each container
        for tool in pl.EXTERNAL_TOOLS:
            rows = self.ledger(tool)
            self.assertEqual([r["sample_id"] for r in rows], [sample_id(i) for i in range(len(SAMPLES))])
            for row in rows:
                self.assertEqual(list(row), [key for key, _ in schema_003()])
                self.assertEqual(row["runner"]["template_sha256"],
                                 utf8_sha256(self.world.config["stages"]["repair"]["external_tool_commands"][tool]))
                self.assertEqual((row["stage_runtime_sha256"], row["invocation_sha256"]),
                                 (binding_sha("runtime", tool, MODEL), binding_sha("invocation", tool, MODEL)))
        self.assertEqual({(t, s) for t, s in CALLS if t in pl.EXTERNAL_TOOLS}, self.applicable(pl.EXTERNAL_TOOLS))
        # (8) the ledgers are accepted by the presence semantics: nothing is missing
        self.assertEqual(pg.missing_static(self.root, self.world.config, self.world.target), OrderedDict())
        stages, _findings = pp.target_plan(self.root, self.world.config, self.world.target, with_enhanced=False)
        self.assertEqual([stages[s]["items"] for s in pp.STATIC_STAGES], [0, 0, 0])
        # missing-only: nothing left, so no container is started at all
        self.assertEqual(ms.run_external(self.root, self.world.config, self.authority, self.world.target,
                                         "llov", log=self.logs.append, runner=runner), 0)
        self.assertEqual(len(runner.commands), 2)

    def test_exit_code_mapping(self):
        for code, error in ((1, pl.TargetFailure), (2, EnvironmentError), (3, pl.GlobalStop),
                            (4, pl.GlobalStop), (5, pl.GlobalStop), (0, pl.TargetFailure)):
            seen = []

            def runner(command, **kwargs):
                seen.append((command, kwargs))
                return subprocess.CompletedProcess(command, code)

            with self.subTest(code=code):
                with self.assertRaises(error):  # exit 0 that leaves rows missing is a target failure
                    ms.run_external(self.root, self.world.config, self.authority, self.world.target, "llov",
                                    log=self.logs.append, runner=runner)
                self.assertEqual(len(seen), 1)
                self.assertNotIn(self.token, seen[0][0])
                self.assertEqual(seen[0][1]["env"][sw.TOKEN_ENV], self.token)
        self.assertEqual(sorted(ex.GLOBAL_CONFLICT_EXITS), [3, 4, 5])

    def test_real_container_exits_map_through_the_driver(self):
        UNAVAILABLE.add("parcoach")
        runner = InProcessContainer(self)
        with self.assertRaises(EnvironmentError):  # the container's environment gate (exit 2)
            ms.run_external(self.root, self.world.config, self.authority, self.world.target, "parcoach",
                            runner=runner, log=self.logs.append)
        UNAVAILABLE.clear()
        for authority, code in ((FakeContainerAuthority(self.world.table.sha256, refuse="binding broken"), 4),
                                (FakeContainerAuthority(self.world.table.sha256, drift=True), 5),
                                (FakeContainerAuthority("f" * 64), 4)):  # another frozen table
            runner = InProcessContainer(self, authority)
            with self.assertRaises(pl.GlobalStop):
                ms.run_external(self.root, self.world.config, self.authority, self.world.target, "parcoach",
                                runner=runner, log=self.logs.append)
            self.assertEqual(runner.codes, [code])
        self.assertEqual(self.ledger("parcoach"), [])

    def test_missing_host_repo_is_an_environment_stop(self):
        started = []

        def runner(command, **kwargs):
            started.append(command)
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.dict(os.environ, {"PAREVAL_HOST_REPO": ""}):
            with self.assertRaises(EnvironmentError):
                ms.run_external(self.root, self.world.config, self.authority, self.world.target, "llov",
                                log=self.logs.append, runner=runner)
        self.assertEqual(started, [])

    def test_base_exception_kills_the_named_container(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            if isinstance(command, str):
                raise SimulatedCrash("operator pressed Ctrl-C")
            return subprocess.CompletedProcess(command, 0)

        with self.assertRaises(SimulatedCrash):
            ms.run_external(self.root, self.world.config, self.authority, self.world.target, "parcoach",
                            runner=runner, log=self.logs.append)
        self.assertEqual(calls[1], ["docker", "kill", ms.container_name(self.world.target, "parcoach")])

    def test_driver_refusals_before_any_container(self):
        calls = []
        runner = lambda command, **kwargs: calls.append(command)  # noqa: E731
        with self.assertRaises(pl.GlobalStop):
            ms.run_external(self.root, self.world.config, self.authority, self.world.static_target, "llov",
                            runner=runner, log=self.logs.append)
        with self.assertRaises(pl.GlobalStop):
            ms.run_external(self.root, self.world.config, self.authority, self.world.target, "cppcheck",
                            runner=runner, log=self.logs.append)
        self.authority.token = "0" * 32
        with self.assertRaises(pl.GlobalStop):
            ms.run_external(self.root, self.world.config, self.authority, self.world.target, "llov",
                            runner=runner, log=self.logs.append)
        self.assertEqual((calls, self.phase2_files()), ([], []))

    def test_entrypoint_refusals_before_any_write(self):
        authority = FakeContainerAuthority(self.world.table.sha256)
        refused = [self.args(run_id="full_ext_recovery_004"), self.args(profile="recovery_successor_004"),
                   self.args(target_id=self.world.static_target.target_id),
                   self.args(target_id="%s/full_ext_recovery_009__test_feedback__iter1" % MODEL),
                   self.args(target_id="glm_5_2/%s" % SOURCE_RUN), self.args(tool="cppcheck")]
        with mock.patch.object(LOAD_CONFIG, "load_dotenv", lambda *a, **k: None):
            with mock.patch.dict(os.environ, {sw.TOKEN_ENV: self.token}):
                for args in refused:
                    with self.assertRaises(RecoveryRefused, msg=str(args)):
                        ex.run(args, root=self.root, authority=authority, log=self.logs.append)
            with mock.patch.dict(os.environ, {sw.TOKEN_ENV: "0" * 32}):
                with self.assertRaises(RecoveryRefused):
                    ex.run(self.args(), root=self.root, authority=authority, log=self.logs.append)
            with mock.patch.dict(os.environ, {sw.TOKEN_ENV: self.token}):
                self.assertEqual(ex.run(self.args(), root=self.root, authority=authority, log=self.logs.append), 4)
        self.assertEqual(authority.enforced, [("parcoach", MODEL)])

    def test_main_exit_codes(self):
        argv = ["--config", pl.CONFIG_REL, "--profile", pl.PROFILE, "--run-id", pl.SUCCESSOR,
                "--target-id", self.world.target.target_id, "--tool", "llov"]
        cases = ((None, 0), (EnvironmentError("gate"), 2), (provenance.StaticMergeConflict("merge"), 3),
                 (RecoveryRefused("refused"), 4), (pl.GlobalStop("integrity"), 4),
                 (stage_runtime.StageRuntimeDrift("static.llov", "llov", "a", "b", ["image_id"]), 5),
                 (effective_invocation.InvocationRefused("drift"), 5), (pl.TargetFailure("crash"), 1))
        for error, code in cases:
            with self.subTest(code=code, error=type(error).__name__):
                with mock.patch.object(ex, "run", side_effect=error), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(ex.main(argv), code)

    def test_container_authority_refuses_without_a_persisted_authorization(self):
        authority = ex.ContainerAuthority(self.world.config, self.root / pl.CONFIG_REL, self.root)
        with self.assertRaises(RecoveryRefused) as raised:
            authority.validate()
        self.assertIn("authorization", str(raised.exception))


class ModuleHygieneTests(unittest.TestCase):
    MODULES = ("measure_static.py", "external.py")

    def test_python38_syntax(self):
        for name in self.MODULES:
            source = (Path(__file__).resolve().parent / name).read_text(encoding="utf-8")
            ast.parse(source, name, feature_version=(3, 8))
            self.assertIn("from __future__ import annotations", source)

    def test_no_provider_modules_are_imported(self):
        probe = ("import sys\n"
                 "import thesis.recovery_successor_005.measure_static\n"
                 "import thesis.recovery_successor_005.external\n"
                 "bad = sorted(m for m in sys.modules if m.split('.')[0] in "
                 "('anthropic', 'openai', 'google') or m.startswith('thesis.generation.adapters'))\n"
                 "print(bad)\n"
                 "sys.exit(1 if bad else 0)\n")
        result = subprocess.run([sys.executable, "-B", "-c", probe], cwd=str(REPO_ROOT),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
