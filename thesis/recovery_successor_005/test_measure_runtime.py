"""Synthetic tests of the phase-2 runtime backfill (measure_runtime.py).

Native equivalence with a stubbed run_correctness.run_sample and stub dynamic
tools registered under the configured names, missing-only presence, crash /
torn-tail resume, stop(), refusals and the environment gates. No compiler,
no analyzer, no provider; every repository is a temp dir.

    python3 -B -m unittest -v thesis.recovery_successor_005.test_measure_runtime
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from collections import OrderedDict
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

from thesis.evaluation import framework
from thesis.evaluation import run_correctness as rc
from thesis.evaluation import run_dynamic_analysis as rda
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import measure_runtime as mr
from thesis.recovery_successor_005 import targets as pt

REPO = Path(__file__).resolve().parents[2]
# the real phase-2 config (JSON content; load_config would read .env)
CONFIG = json.loads((REPO / pl.CONFIG_REL).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
MODEL = "claude_opus_5"
ITER1 = "full_ext_recovery_001__static_feedback__iter1"
ITER2 = "full_ext_recovery_003__static_feedback__iter2"
TEST1 = "full_ext_recovery_001__test_feedback__iter1"
CELLS = OrderedDict([
    (ITER1, [("scan", "prefix_sum", "serial"), ("scan", "prefix_sum", "omp"), ("scan", "prefix_sum", "mpi"),
             ("sort", "sort_k", "serial"), ("reduce", "sum", "omp")]),
    (ITER2, [("scan", "prefix_sum", "omp"), ("sort", "sort_k", "mpi")]),
    (TEST1, [("scan", "prefix_sum", "serial")]),
])
LOOPS = {ITER1: ("static_feedback", 1, "full_ext_recovery_001"),
         ITER2: ("static_feedback", 2, "full_ext_recovery_003"),
         TEST1: ("test_feedback", 1, "full_ext_recovery_001")}
DYNAMIC_TOOLS = ("asan_ubsan", "tsan", "memcheck", "must")


def sample_id(cell):
    return "%s__%s__%s__%s__sample_0" % ((MODEL,) + tuple(cell))


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_rows(path):
    if not Path(path).is_file():
        return []
    return [json.loads(line, object_pairs_hook=OrderedDict)
            for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def native_part(row, drop=()):
    """A phase-2 row without the phase-2 additions (and `drop`)."""
    return OrderedDict((k, v) for k, v in row.items()
                       if k not in pg.PROVENANCE_FIELDS and k != "phase2_binding" and k not in drop)


def context(root, config):
    root = Path(root).resolve()
    return framework.EvaluationContext(repo_root=root, drivers_cpp_dir=root / "drivers" / "cpp",
                                       primary_compiler="g++", config=config)


class FakeAuthority:
    """The lead's authority interface (check / enforce / binding / token)."""

    def __init__(self, token):
        self.token = token
        self.checks = 0
        self.enforced = []

    def check(self):
        self.checks += 1

    def binding(self, stage, model):
        def digest(label):
            return canonical_sha256([label, stage, model])
        return OrderedDict([("contract_sha256", "c" * 64), ("authorization_sha256", "a" * 64),
                            ("stage_runtime_sha256", digest("runtime")),
                            ("invocation_sha256", digest("invocation"))])

    def enforce(self, stage, model):
        self.enforced.append((stage, model))
        return dict(self.binding(stage, model), enforced=True)


class World:
    """A synthetic repository: three targets of one model (two static_feedback,
    one test_feedback), a frozen table, a held writer lock."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        (self.root / "drivers/cpp/models").mkdir(parents=True)
        documents = []
        for run, cells in CELLS.items():
            rows = []
            for index, cell in enumerate(cells):
                sid = sample_id(cell)
                relative = "%s/sources/%s/generated-code.hpp" % (pt.run_dir(run, MODEL), sid)
                data = ("// %s %s\nint f() { return %d; }\n" % (run, sid, index)).encode("utf-8")
                (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
                (self.root / relative).write_bytes(data)
                rows.append(OrderedDict([
                    ("run_id", run), ("model_id", MODEL), ("sample_id", sid), ("execution_model", cell[2]),
                    ("benchmark", "%s/%s" % cell[:2]), ("assembled", True), ("source_path", relative),
                    ("source_sha256", hashlib.sha256(data).hexdigest()),
                    ("drivers", OrderedDict([("benchmark_dir", "drivers/cpp/benchmarks/%s/%s" % cell[:2]),
                                             ("model_driver", "drivers/cpp/models/%s-driver.cc" % cell[2])]))]))
                if index == 1:  # a skipped generation has no source and is never a sample
                    rows.append(OrderedDict([("run_id", run), ("model_id", MODEL), ("assembled", False),
                                             ("sample_id", sample_id(("skip", "me", "serial")))]))
            write_jsonl(self.root / pt.run_dir(run, MODEL) / "assembly.jsonl", rows)
            samples, assembly = pt._samples(self.root, run, MODEL)
            variant, iteration, owner = LOOPS[run]
            documents.append(pt._target(MODEL, variant, iteration, run, owner, "native", samples, assembly))
        document = OrderedDict([("schema_version", pt.SCHEMA), ("run_id", pl.SUCCESSOR),
                                ("model_ids", list(pl.MODELS)), ("targets", documents)])
        document["table_sha256"] = canonical_sha256(document)
        self.table = pt.TargetTable(self.root, document)
        self.token = sw.WriterLock(self.root, pl.SUCCESSOR, "test").acquire()
        self.authority = FakeAuthority(self.token)
        self.logs = []

    def log(self, line):
        self.logs.append(line)

    def static_targets(self):
        return self.table.select(variant="static_feedback")

    def target(self, run):
        return self.table.get("%s/%s" % (MODEL, run))

    def ids(self, run):
        return list(self.target(run).samples)

    def ledger_file(self, run, name):
        return self.root / pt.ledger_relative(MODEL, run, name)

    def ledger(self, run, name):
        return read_rows(self.ledger_file(run, name))

    def invocations(self):
        return read_rows(self.root / pl.RESULTS_REL / MODEL / mr.INVOCATIONS_FILE)

    def historical(self, run, name, rows):
        write_jsonl(self.root / pt.run_dir(run, MODEL) / name, rows)

    def snapshot(self):
        return sorted((p.relative_to(self.root).as_posix(), p.stat().st_size if p.is_file() else -1)
                      for p in self.root.rglob("*"))

    def twin(self, destination):
        shutil.copytree(str(self.root), str(destination))
        return Path(destination).resolve()

    def correctness(self, recorder, config=CONFIG, targets=None, stop=None, gate=None):
        gate = gate or mock.Mock(return_value=[])
        with mock.patch.object(rc, "run_sample", recorder), mock.patch.object(rc, "missing_toolchain", gate):
            return mr.run_correctness(self.root, config, self.table, self.authority, targets,
                                      log=self.log, stop=stop)

    def dynamic(self, config=CONFIG, targets=None, stop=None):
        return mr.run_dynamic(self.root, config, self.table, self.authority, targets, log=self.log, stop=stop)


class RunSampleRecorder:
    """Stand-in for run_correctness.run_sample: records every call argument
    (paths repo-relative) and returns a deterministic native-shaped record."""
    VERDICTS = {"serial": "pass", "omp": "timeout", "mpi": "build_failed"}

    def __init__(self, fail_at=None, on_call=None):
        self.calls = []
        self.fail_at = fail_at
        self.on_call = on_call

    def ids(self):
        return [call["sample_id"] for call in self.calls]

    def __call__(self, sample, ctx, launch_overrides, niter, build_timeout, run_timeout, *extra, **options):
        root = Path(ctx.repo_root)
        self.calls.append(OrderedDict([
            ("sample_id", sample.sample_id), ("run_id", sample.run_id), ("model_id", sample.model_id),
            ("execution_model", sample.execution_model), ("problem_type", sample.problem_type),
            ("name", sample.name), ("source_path", Path(sample.source_path).relative_to(root).as_posix()),
            ("benchmark_dir", Path(sample.benchmark_dir).relative_to(root).as_posix()),
            ("model_driver_file", sample.model_driver_file), ("assembly_entry", dict(sample.assembly_entry)),
            ("drivers_cpp_dir", Path(ctx.drivers_cpp_dir).relative_to(root).as_posix()),
            ("primary_compiler", ctx.primary_compiler), ("config", ctx.config),
            ("launch_overrides", launch_overrides), ("niter", niter), ("build_timeout", build_timeout),
            ("run_timeout", run_timeout), ("extra", extra), ("options", options)]))
        if self.on_call is not None:
            self.on_call(len(self.calls), sample)
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise RuntimeError("killed while measuring " + sample.sample_id)
        verdict = self.VERDICTS[sample.execution_model]
        record = {"schema_version": rc.CORRECTNESS_SCHEMA_VERSION, "run_id": sample.run_id,
                  "model_id": sample.model_id, "sample_id": sample.sample_id,
                  "execution_model": sample.execution_model, "created_at_utc": "2026-10-13T00:00:00Z",
                  "compile": {"ok": verdict != "build_failed", "stderr": "" if verdict != "build_failed" else "e"}}
        if verdict == "build_failed":
            record["runs"] = []
            record["verdict"] = verdict
            record["run_verdicts"] = {}
            return record
        record["runs"] = [{"params": {"threads": 1}, "argv": ["./benchmark.out", str(niter)], "exit_code": 0,
                           "timed_out": verdict == "timeout", "verdict": verdict, "stdout": "Validation: PASS"}]
        record["run_verdicts"] = {verdict: 1}
        record["verdict"] = verdict
        return record


class StubDynamicTool:
    """Deterministic dynamic tool: findings (blocking + pre-marked low
    confidence) on `scan`, a TOOL_ERROR of memcheck on `reduce`, clean else."""

    def __init__(self, name, available=True, fail_at=None):
        self.name = name
        self.available = available
        self.fail_at = fail_at
        self.calls = []

    def is_available(self):
        return self.available

    def run(self, sample, ctx):
        self.calls.append(sample.sample_id)
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise RuntimeError("killed inside " + self.name)
        if self.name == "memcheck" and sample.problem_type == "reduce":
            return framework.ToolResult(tool=self.name, ran=True, exit_code=1, duration_seconds=2.71828,
                                        raw_stderr="valgrind: internal error", error="valgrind crashed",
                                        analysis_state=framework.STATE_TOOL_ERROR,
                                        analysis_gap_reason="tool crashed")
        findings = []
        if sample.problem_type == "scan":
            findings.append(framework.Finding(tool=self.name, check_id=self.name + ".planted", severity="error",
                                              message="planted in " + sample.sample_id,
                                              file="generated-code.hpp", line=3, column=5, blocking=True))
            findings.append(framework.Finding(tool=self.name, check_id="hint.note", severity="note",
                                              message="hint", low_confidence=True))
        return framework.ToolResult(tool=self.name, ran=True, exit_code=0, duration_seconds=0.12345,
                                    findings=findings, raw_stdout="stdout of " + sample.sample_id,
                                    analysis_state=framework.STATE_COMPLETED, analysis_details={"runs": 1})


class PreflightFailingTool(StubDynamicTool):
    def preflight(self):
        return "vm.mmap_rnd_bits too high: run sysctl vm.mmap_rnd_bits=28"


def stub_tools(names=DYNAMIC_TOOLS, **options):
    return OrderedDict((name, StubDynamicTool(name, **options.get(name, {}))) for name in names)


@contextmanager
def registry(tools):
    """Swap the framework registry for `tools` (restored afterwards); the
    native register_dynamic_tools registers exactly these stubs."""
    def register():
        for tool in tools.values():
            framework.register_tool(tool)

    rda.reset_preflight_cache()
    try:
        with mock.patch.dict(framework._TOOL_REGISTRY, {}, clear=True), \
                mock.patch.object(rda, "register_dynamic_tools", register):
            register()
            yield tools
    finally:
        rda.reset_preflight_cache()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(Path(self.tmp.name) / "repo")

    def assert_phase2_fields(self, world, run, row, stage):
        target = world.target(run)
        for key, value in pt.provenance(target, row["sample_id"]).items():
            self.assertEqual(value, row[key])
        self.assertEqual(world.authority.binding(stage, MODEL), row["phase2_binding"])
        self.assertEqual(list(pg.PROVENANCE_FIELDS) + ["phase2_binding"], list(row)[-8:])


# (1) correctness equivalence --------------------------------------------------------

class CorrectnessEquivalence(Base):
    def test_same_run_sample_calls_and_records_as_native_run_model(self):
        custom = copy.deepcopy(CONFIG)
        overrides = {"omp": {"threads": [1, 2]}, "mpi": {"ranks": [2]}}
        custom["stages"]["correctness_tests"].update(niter=3, run_timeout_seconds=77, build_timeout_seconds=55,
                                                     launch_overrides=overrides)
        for index, (config, values) in enumerate(((CONFIG, (None, 1, 120.0, 120.0)),
                                                  (custom, (overrides, 3, 55.0, 77.0)))):
            with self.subTest(values=values):
                world = World(Path(self.tmp.name) / ("repo%d" % index))
                twin = world.twin(Path(self.tmp.name) / ("native%d" % index))
                native = RunSampleRecorder()
                with mock.patch.object(rc, "run_sample", native), redirect_stdout(io.StringIO()):
                    for target in world.static_targets():
                        rc.run_model(context=context(twin, config), intermediate_dir=twin / pt.INTERMEDIATE_REL,
                                     run_id=target.source_run, model_id=MODEL,
                                     output_file_name="correctness.jsonl", launch_overrides=values[0],
                                     niter=values[1], build_timeout=values[2], run_timeout=values[3],
                                     invocation_label="run_correctness")
                ours = RunSampleRecorder()
                gate = mock.Mock(return_value=[])
                counts = world.correctness(ours, config=config, gate=gate)

                gate.assert_called_once_with(["serial", "omp", "mpi"], "g++")
                self.assertEqual(7, len(native.calls))
                self.assertEqual(native.calls, ours.calls)
                for run in (ITER1, ITER2):
                    expected = read_rows(twin / pt.run_dir(run, MODEL) / "correctness.jsonl")
                    rows = world.ledger(run, pt.CORRECTNESS_FILE)
                    self.assertEqual(expected, [native_part(row) for row in rows])
                    for row, native_row in zip(rows, expected):
                        self.assertEqual(list(native_row), list(row)[:len(native_row)])
                        self.assert_phase2_fields(world, run, row, "correctness")
                self.assertFalse(world.ledger_file(TEST1, pt.CORRECTNESS_FILE).parent.exists())
                self.assertEqual(7, counts["written"])
                self.assertEqual((2, 1, 0), (counts["targets"], counts["skipped_unassigned"], counts["present"]))
                self.assertEqual((2, 3, 2), (counts["verdict.pass"], counts["verdict.timeout"],
                                             counts["verdict.build_failed"]))
                self.assertEqual([("correctness", MODEL)], world.authority.enforced)
                self.assertEqual(2, world.authority.checks)
                history = world.invocations()
                self.assertEqual([(ITER1, "invoked"), (ITER1, "completed"), (ITER2, "invoked"), (ITER2, "completed")],
                                 [(row["candidate_source_run"], row["status"]) for row in history])
                self.assertEqual(1, len(set(row["invocation_id"] for row in history)))
                self.assertEqual([5, 2], [row["counts"]["written"] for row in history[1::2]])
                self.assertTrue(all(row["stage"] == "correctness" and row["completed_at_utc"]
                                    for row in history[1::2]))


# (2) dynamic equivalence ------------------------------------------------------------

class DynamicEquivalence(Base):
    def test_same_records_as_native_run_model_with_stub_tools(self):
        world = self.world
        twin = world.twin(Path(self.tmp.name) / "native")
        with registry(stub_tools()) as native, redirect_stdout(io.StringIO()):
            settings = rda.resolve_enabled_tools(CONFIG, None)
            for target in world.static_targets():
                rda.run_model(context=context(twin, CONFIG), intermediate_dir=twin / pt.INTERMEDIATE_REL,
                              run_id=target.source_run, model_id=MODEL, tool_settings=settings,
                              output_file_name="dynamic_analysis.jsonl", tools_skipped=[],
                              skip_unavailable_tools=False,
                              invocation_label="run_dynamic_analysis --tools <config>")
        with registry(stub_tools()) as ours:
            counts = world.dynamic()

        self.assertEqual(dict((n, t.calls) for n, t in native.items()), dict((n, t.calls) for n, t in ours.items()))
        for run in (ITER1, ITER2):
            expected = read_rows(twin / pt.run_dir(run, MODEL) / "dynamic_analysis.jsonl")
            rows = world.ledger(run, pt.DYNAMIC_FILE)
            self.assertEqual(world.ids(run), [row["sample_id"] for row in rows])
            self.assertEqual([native_part(row, ["created_at_utc"]) for row in expected],
                             [native_part(row, ["created_at_utc"]) for row in rows])
            for row, native_row in zip(rows, expected):
                self.assertEqual(list(native_row), list(row)[:len(native_row)])  # key order incl. created_at
                self.assertTrue(row["created_at_utc"])
                self.assert_phase2_fields(world, run, row, "dynamic")
        rows = OrderedDict((row["sample_id"], row) for row in world.ledger(ITER1, pt.DYNAMIC_FILE))
        serial = rows[sample_id(("scan", "prefix_sum", "serial"))]
        self.assertEqual(list(DYNAMIC_TOOLS), list(serial["tools"]))
        self.assertEqual(("NOT_APPLICABLE", "NOT_APPLICABLE"),
                         (serial["tools"]["tsan"]["analysis_state"], serial["tools"]["must"]["analysis_state"]))
        self.assertNotIn("num_low_confidence", serial["tools"]["tsan"])
        self.assertEqual((True, 2), (serial["has_blocking_findings"], serial["low_confidence_count"]))
        crashed = rows[sample_id(("reduce", "sum", "omp"))]["tools"]["memcheck"]
        self.assertEqual(("TOOL_ERROR", "valgrind crashed"), (crashed["analysis_state"], crashed["error"]))
        self.assertEqual((7, 1, 1), (counts["written"], counts["tool_errors.memcheck"], counts["skipped_unassigned"]))
        self.assertEqual([("dynamic", MODEL)], world.authority.enforced)

    def test_unregistered_tool_is_skipped_like_main(self):
        with registry(stub_tools(("asan_ubsan", "tsan", "memcheck"))):
            counts = self.world.dynamic(targets=[self.world.target(ITER2)])
        self.assertIn("Tool 'must' configured but not implemented yet, skipping.", self.world.logs)
        rows = self.world.ledger(ITER2, pt.DYNAMIC_FILE)
        self.assertEqual([["asan_ubsan", "tsan", "memcheck"]] * 2, [list(row["tools"]) for row in rows])
        self.assertEqual(2, counts["written"])


# (3) missing-only -------------------------------------------------------------------

class MissingOnly(Base):
    def test_correctness_history_and_phase2_rows_are_never_remeasured(self):
        world = self.world
        ids = world.ids(ITER1)
        world.historical(ITER1, "correctness.jsonl", [
            {"run_id": ITER1, "model_id": MODEL, "sample_id": ids[0], "verdict": "build_failed", "runs": []},
            {"run_id": ITER1, "model_id": MODEL, "sample_id": ids[1], "verdict": "timeout"}])
        first = RunSampleRecorder()
        counts = world.correctness(first)
        self.assertEqual(ids[2:] + world.ids(ITER2), first.ids())
        self.assertEqual((2, 5), (counts["present"], counts["written"]))
        before = [world.ledger_file(run, pt.CORRECTNESS_FILE).read_bytes() for run in (ITER1, ITER2)]
        invocations = len(world.invocations())

        again = RunSampleRecorder()
        counts = world.correctness(again)
        self.assertEqual([], again.calls)
        self.assertEqual((7, 0, 2), (counts["present"], counts["written"], counts["targets_complete"]))
        self.assertEqual(before, [world.ledger_file(run, pt.CORRECTNESS_FILE).read_bytes() for run in (ITER1, ITER2)])
        self.assertEqual(invocations, len(world.invocations()))

        # a phase-2 row that a historical record now duplicates is an integrity stop, nothing written
        world.historical(ITER1, "correctness.jsonl", [
            {"run_id": ITER1, "model_id": MODEL, "sample_id": sid, "verdict": "pass"} for sid in ids[:3]])
        snapshot = world.snapshot()
        with self.assertRaises(pl.GlobalStop):
            world.correctness(RunSampleRecorder())
        self.assertEqual(snapshot, world.snapshot())

    def test_dynamic_tool_error_entries_count_as_present(self):
        world = self.world
        ids = world.ids(ITER1)
        world.historical(ITER1, "dynamic_analysis.jsonl", [
            {"run_id": ITER1, "model_id": MODEL, "sample_id": ids[0],
             "tools": {"memcheck": {"analysis_state": "TOOL_ERROR", "ran": True, "error": "x"}}}])
        with registry(stub_tools()) as tools:
            counts = world.dynamic()
        self.assertEqual(ids[1:] + world.ids(ITER2), tools["asan_ubsan"].calls)
        self.assertEqual((1, 6), (counts["present"], counts["written"]))
        reduce_row = [r for r in world.ledger(ITER1, pt.DYNAMIC_FILE) if r["sample_id"] == ids[4]][0]
        self.assertEqual("TOOL_ERROR", reduce_row["tools"]["memcheck"]["analysis_state"])
        before = world.ledger_file(ITER1, pt.DYNAMIC_FILE).read_bytes()
        with registry(stub_tools()) as tools:
            counts = world.dynamic()
        self.assertEqual([], [call for tool in tools.values() for call in tool.calls])
        self.assertEqual((7, 0), (counts["present"], counts["written"]))
        self.assertEqual(before, world.ledger_file(ITER1, pt.DYNAMIC_FILE).read_bytes())


# (4) crash / resume ---------------------------------------------------------------

class CrashResume(Base):
    def test_kill_after_k_samples_torn_tail_archived_resume_writes_the_rest(self):
        world = self.world
        ids = world.ids(ITER1)
        with self.assertRaises(RuntimeError):
            world.correctness(RunSampleRecorder(fail_at=3))
        self.assertEqual(ids[:2], [row["sample_id"] for row in world.ledger(ITER1, pt.CORRECTNESS_FILE)])
        self.assertEqual(["invoked"], [row["status"] for row in world.invocations()])
        ledger = world.ledger_file(ITER1, pt.CORRECTNESS_FILE)
        with ledger.open("ab") as handle:  # the kill hit the next append
            handle.write(b'{"schema_version": "correctness.v1", "run_id": "full_ext_rec')

        resumed = RunSampleRecorder()
        counts = world.correctness(resumed)
        self.assertEqual(ids[2:] + world.ids(ITER2), resumed.ids())
        self.assertEqual(ids, [row["sample_id"] for row in world.ledger(ITER1, pt.CORRECTNESS_FILE)])
        self.assertEqual(world.ids(ITER2), [row["sample_id"] for row in world.ledger(ITER2, pt.CORRECTNESS_FILE)])
        self.assertEqual((2, 5), (counts["present"], counts["written"]))
        torn = read_rows(ledger.with_name(ledger.name + ".torn"))
        self.assertEqual(1, len(torn))
        self.assertTrue(torn[0]["text"].startswith('{"schema_version": "correctness.v1"'))
        self.assertTrue(any(line.startswith("archived a torn tail") for line in world.logs))
        history = world.invocations()
        self.assertEqual(["invoked", "invoked", "completed", "invoked", "completed"], [r["status"] for r in history])
        self.assertNotEqual(history[0]["invocation_id"], history[1]["invocation_id"])
        self.assertEqual(3, history[2]["counts"]["written"])
        self.assertEqual(7, len(pg.present_records(world.root, world.target(ITER1), pt.CORRECTNESS_FILE))
                         + len(pg.present_records(world.root, world.target(ITER2), pt.CORRECTNESS_FILE)))

    def test_dynamic_kill_inside_a_tool_resumes_missing_only(self):
        world = self.world
        with registry(stub_tools(asan_ubsan={"fail_at": 4})):
            with self.assertRaises(RuntimeError):
                world.dynamic()
        self.assertEqual(world.ids(ITER1)[:3], [r["sample_id"] for r in world.ledger(ITER1, pt.DYNAMIC_FILE)])
        with registry(stub_tools()) as tools:
            counts = world.dynamic()
        self.assertEqual(world.ids(ITER1)[3:] + world.ids(ITER2), tools["asan_ubsan"].calls)
        self.assertEqual((3, 4), (counts["present"], counts["written"]))
        self.assertEqual(world.ids(ITER1), [r["sample_id"] for r in world.ledger(ITER1, pt.DYNAMIC_FILE)])


# (5) stop() ------------------------------------------------------------------------

class Stop(Base):
    def test_stop_is_honoured_between_samples_and_between_targets(self):
        world = self.world
        ids = world.ids(ITER1)
        first = RunSampleRecorder()
        counts = world.correctness(first, stop=lambda: len(first.calls) >= 2)
        self.assertEqual((1, 2), (counts["stopped"], counts["written"]))
        self.assertEqual(ids[:2], [r["sample_id"] for r in world.ledger(ITER1, pt.CORRECTNESS_FILE)])
        self.assertEqual(["invoked", "stopped"], [r["status"] for r in world.invocations()])
        self.assertEqual(2, world.invocations()[-1]["counts"]["written"])

        second = RunSampleRecorder()  # the target finishes, the next one never starts
        counts = world.correctness(second, stop=lambda: len(second.calls) >= 3)
        self.assertEqual(ids[2:], second.ids())
        self.assertEqual((1, 3), (counts["stopped"], counts["written"]))
        self.assertEqual([], world.ledger(ITER2, pt.CORRECTNESS_FILE))
        self.assertEqual("completed", world.invocations()[-1]["status"])

        third = RunSampleRecorder()
        counts = world.correctness(third)
        self.assertEqual(world.ids(ITER2), third.ids())
        self.assertEqual(0, counts["stopped"])


# (6) refusals ---------------------------------------------------------------------

class Refusals(Base):
    def fresh(self, name):
        return World(Path(self.tmp.name) / name)

    def test_wrong_token_refuses_before_any_write(self):
        world = self.world
        world.authority.token = "0" * 32
        snapshot = world.snapshot()
        recorder = RunSampleRecorder()
        with self.assertRaises(pl.GlobalStop):
            world.correctness(recorder)
        self.assertEqual(([], snapshot), (recorder.calls, world.snapshot()))

    def test_token_lost_during_a_run_refuses_the_next_append(self):
        world = self.world

        def revoke(number, sample):
            if number == 2:
                world.authority.token = "f" * 32

        with self.assertRaises(pl.GlobalStop):
            world.correctness(RunSampleRecorder(on_call=revoke))
        self.assertEqual(world.ids(ITER1)[:1], [r["sample_id"] for r in world.ledger(ITER1, pt.CORRECTNESS_FILE)])

    def test_source_drift_before_the_target_refuses_without_writing(self):
        world = self.world
        source = world.root / world.target(ITER1).samples[world.ids(ITER1)[3]]["source_path"]
        source.write_bytes(source.read_bytes() + b"// drift\n")
        snapshot = world.snapshot()
        recorder = RunSampleRecorder()
        with self.assertRaises(pl.GlobalStop):
            world.correctness(recorder)
        self.assertEqual(([], snapshot), (recorder.calls, world.snapshot()))

    def test_source_drift_during_the_measurement_discards_it(self):
        world = self.world

        def drift(number, sample):
            if number == 2:
                Path(sample.source_path).write_bytes(b"// replaced while measured\n")

        with self.assertRaises(pl.GlobalStop):
            world.correctness(RunSampleRecorder(on_call=drift))
        self.assertEqual(world.ids(ITER1)[:1], [r["sample_id"] for r in world.ledger(ITER1, pt.CORRECTNESS_FILE)])

    def test_foreign_or_excluded_target_and_renamed_output_refuse_before_anything(self):
        world = self.world
        foreign = copy.deepcopy(world.target(ITER1).document)
        foreign["samples"] = foreign["samples"][:2]
        excluded = copy.deepcopy(world.target(ITER1).document)
        excluded.update(source_run=pl.EXCLUDED_HISTORICAL_RUNS[0],
                        target_id="%s/%s" % (MODEL, pl.EXCLUDED_HISTORICAL_RUNS[0]))
        renamed = copy.deepcopy(CONFIG)
        renamed["stages"]["correctness_tests"]["output_file_name"] = "correctness_v2.jsonl"
        snapshot = world.snapshot()
        for label, config, targets in (("foreign", CONFIG, [pt.Target(foreign)]),
                                       ("excluded", CONFIG, [pt.Target(excluded)]),
                                       ("renamed", renamed, None)):
            with self.subTest(label):
                recorder = RunSampleRecorder()
                with self.assertRaises(pl.GlobalStop):
                    world.correctness(recorder, config=config, targets=targets)
                self.assertEqual(([], 0, snapshot), (recorder.calls, world.authority.checks, world.snapshot()))


# (7) environment gates ---------------------------------------------------------------

class EnvironmentGates(Base):
    def test_correctness_toolchain_gate_raises_before_any_file(self):
        world = self.world
        snapshot = world.snapshot()
        recorder = RunSampleRecorder()
        gate = mock.Mock(return_value=["mpirun (mpi launches)"])
        with self.assertRaises(EnvironmentError) as raised:
            world.correctness(recorder, gate=gate)
        self.assertIn("mpirun", str(raised.exception))
        self.assertEqual(([], 0, snapshot), (recorder.calls, world.authority.checks, world.snapshot()))

    def test_dynamic_preflight_gate_raises_before_any_file(self):
        world = self.world
        snapshot = world.snapshot()
        unavailable = stub_tools(must={"available": False})
        failing = stub_tools()
        failing["tsan"] = PreflightFailingTool("tsan")
        for label, tools, text in (("unavailable", unavailable, "[must]"),
                                   ("preflight", failing, "vm.mmap_rnd_bits"),
                                   ("none registered", OrderedDict(), "No usable dynamic tools")):
            with self.subTest(label), registry(tools):
                with self.assertRaises(EnvironmentError) as raised:
                    world.dynamic()
                self.assertIn(text, str(raised.exception))
                self.assertEqual([], [call for tool in tools.values() for call in tool.calls])
                self.assertEqual((0, snapshot), (world.authority.checks, world.snapshot()))


if __name__ == "__main__":
    unittest.main()
