"""Synthetic tests of the phase-2 enhanced wrapper (measure_enhanced).

A temp repository holds a tiny benchmark tree (drivers/cpp/benchmarks/
<pt>/<name>/cpu.cc, two parameterizable real benchmark names + one without
the ENHANCED_TEST_SIZE_DEFAULT marker), assemblies, candidate sources and
the writer lock. Only the compilers/binaries behind the native functions are
stubbed (compile_sample, run_binary, compile_and_run, stability_probe,
build_wrapper, missing_toolchain); precompute_gates and process_sample run
for real, the specs are the real frozen E3 specs and the real
build_benchmark_specs. Proves:
  (1) records/group rows equal those of main()'s native process_sample
      usage (minus created_at_utc and the phase-2 provenance), spec set ==
      ledger.expected_enhanced (20 per parameterizable sample);
  (2) one gate cache for the whole invocation (each spec_key gated once
      across targets and models);
  (3) registration before the first record; changed condition / candidate
      source -> GlobalStop on resume; identical condition -> only missing
      pairs; crash mid-target + torn tail -> archived, resume completes, no
      duplicate (sample, spec);
  (4) jobs from config only, pool sizes == config jobs;
  (5) stop() cancels queued samples cleanly;
  (6) wrong token, source drift, foreign target refuse before writing;
  (7) summary native-shaped and consistent with the ledger.

Main container only (python 3.12).
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import inspect
import json
import sys
import tempfile
import threading
import unittest
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from thesis.config.load_config import load_config
from thesis.enhanced_tests import capabilities
from thesis.enhanced_tests import execution_provenance as execprov
from thesis.enhanced_tests.specs import build_benchmark_specs, spec_key, stage_settings
from thesis.evaluation import framework
from thesis.evaluation import run_enhanced_tests as ret
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import measure_enhanced as me
from thesis.recovery_successor_005 import targets as pt

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = load_config(str(REPO_ROOT / pl.CONFIG_REL))
LU = ("dense_la", "00_dense_la_lu_decomp")
AXPY = ("dense_la", "03_dense_la_axpy")
GEMM = ("dense_la", "02_dense_la_gemm")  # fixture cpu.cc WITHOUT the marker
BASE = pl.PARENT
CAND = "full_ext_recovery_001__static_feedback__iter1"
MODEL_A, MODEL_B = "claude_fable_5", "claude_opus_5"
SAMPLES = ((LU, "serial", 0), (LU, "omp", 0), (AXPY, "serial", 0), (AXPY, "mpi", 0), (GEMM, "serial", 0))
SERIAL_ONLY = ((LU, "serial", 0), (LU, "serial", 1), (AXPY, "serial", 0), (AXPY, "serial", 1))
BINDING = OrderedDict((k, k[0] * 64) for k in me.BINDING_FIELDS)
NATIVE_SUMMARY_KEYS = ["schema_version", "run_id", "model_id", "created_at_utc", "counts", "samples_seen",
                       "resumed_rows", "timing_semantics", "build_groups_file", "legacy_mixed_rows",
                       "effective_config", "enhanced_policy_provenance", "enhanced_execution_provenance",
                       "enhanced_model_execution_provenance"]
PHASE2_FIELDS = tuple(pg.PROVENANCE_FIELDS) + ("phase2_binding",)
ORIGINAL_SPEC_DEFINES = ret.spec_defines
REAL_FINGERPRINT = execprov.enhanced_execution_fingerprint
_FINGERPRINTS = {}


def memo_fingerprint(specs_path, settings, runtime=None, primary_compiler="g++", include_toolchain=True):
    """The REAL global fingerprint, memoised per input (it hashes the real
    harness/benchmarks and probes the toolchain - identical per process)."""
    key = json.dumps([str(specs_path), settings, runtime, primary_compiler, include_toolchain],
                     sort_keys=True, default=str)
    if key not in _FINGERPRINTS:
        _FINGERPRINTS[key] = REAL_FINGERPRINT(specs_path, settings, runtime=runtime,
                                              primary_compiler=primary_compiler,
                                              include_toolchain=include_toolchain)
    return _FINGERPRINTS[key]


def sample_id(model, bench, execution_model, index):
    return "%s__%s__%s__%s__sample_%d" % (model, bench[0], bench[1], execution_model, index)


def pick(*parts):
    return int(hashlib.sha256(json.dumps(parts, default=str).encode("utf-8")).hexdigest(), 16)


def key_of(spec):
    return pg.key_text(spec_key(spec))


def strip(row, fields=("created_at_utc",) + PHASE2_FIELDS):
    return OrderedDict((k, v) for k, v in row.items() if k not in fields)


def normalized(row):
    return json.loads(json.dumps(row), object_pairs_hook=OrderedDict)


class FakeAuthority:
    def __init__(self, token):
        self.token = token
        self.checks = 0
        self.enforced = []

    def check(self):
        self.checks += 1
        return True

    def enforce(self, stage, model):
        self.enforced.append((stage, model))
        return dict(BINDING, enforced=True)

    def binding(self, stage, model):
        return OrderedDict(BINDING)


class Stubs:
    """Deterministic stand-ins for compilers and binaries only."""

    def __init__(self, fail_on=None, on_run=None):
        self.lock = threading.Lock()
        self.gated = Counter()  # key_text -> gate computations (spec_defines runs once per new gate)
        self.wrappers = Counter()
        self.runs = Counter()
        self.fail_on = fail_on  # (sample_id, runs allowed before the failure)
        self.on_run = on_run

    def build_wrapper(self, benchmark_dir, prompt_text):
        self.wrappers[benchmark_dir.name] += 1
        return "// forwarding wrapper %s\n" % benchmark_dir.name

    def spec_defines(self, spec):
        self.gated[key_of(spec)] += 1
        return ORIGINAL_SPEC_DEFINES(spec)

    def compile_and_run(self, benchmark_dir, wrapper, defines, fast_math=False, extra_headers=None):
        return "crash" if pick("gate", benchmark_dir.name, defines, extra_headers) % 9 == 0 else "pass"

    def stability_probe(self, benchmark_dir, prompt_text, defines, extra_headers=None):
        value = pick("stability", benchmark_dir.name, defines, extra_headers) % 11
        return "validate_fail" if value == 0 else ("non_finite_reference" if value == 1 else "pass")

    def compile_sample(self, sample, defines, out_path, extra_include_dir=None, execution_model="serial"):
        size = [d for d in defines if d.startswith("ENHANCED_TEST_SIZE=")][0]
        Path(out_path).write_text(json.dumps({"sample_id": sample.sample_id, "size": size}), encoding="utf-8")
        if pick("build", sample.sample_id, size) % 5 == 0:
            return False, 0.25, "error: stub build failure at %s" % size
        return True, 0.5, ""

    def run_binary(self, binary, cwd, timeout, execution_model="serial", launch_settings=None, extra_env=None,
                   marker_nonce=None):
        built = json.loads(Path(binary).read_text(encoding="utf-8"))
        with self.lock:
            self.runs[built["sample_id"]] += 1
            count = self.runs[built["sample_id"]]
        if self.fail_on and built["sample_id"] == self.fail_on[0] and count > self.fail_on[1]:
            raise RuntimeError("stub harness failure")
        if self.on_run:
            self.on_run(built)
        env = sorted((k, v) for k, v in (extra_env or {}).items() if k != "ENHANCED_FILL_VALUES_FILE")
        status = ("pass", "pass", "fail", "crash", "timeout", "runtime_error",
                  "baseline_incompatible")[pick(built["sample_id"], built["size"], env) % 7]
        stdout = ("MISMATCH index=3 expected=1.5 got=2.5 rel=0.4\nMISMATCH_SUMMARY shown=1 total=4\n"
                  if status == "fail" else "")
        exit_code = None if status == "timeout" else (134 if status == "crash" else 0)
        return status, exit_code, 0.125, stdout, "stub abort" if status == "crash" else ""

    @contextlib.contextmanager
    def installed(self):
        with contextlib.ExitStack() as stack:
            for name in ("build_wrapper", "spec_defines", "compile_and_run", "stability_probe",
                         "compile_sample", "run_binary"):
                stack.enter_context(mock.patch.object(ret, name, getattr(self, name)))
            stack.enter_context(mock.patch.object(ret, "missing_toolchain",
                                                  lambda models, primary_compiler="g++": []))
            stack.enter_context(mock.patch.object(execprov, "enhanced_execution_fingerprint", memo_fingerprint))
            yield self


class Repo:
    """A miniature repository in a temp dir (the real repository is never
    written)."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        for bench in (LU, AXPY):
            self.write("drivers/cpp/benchmarks/%s/%s/cpu.cc" % bench,
                       "#define ENHANCED_TEST_SIZE_DEFAULT 16\n// correct%s()\n" % bench[1])
        self.write("drivers/cpp/benchmarks/%s/%s/cpu.cc" % GEMM, "// fixed-size driver\n")
        self.lock = sw.WriterLock(self.root, pl.SUCCESSOR, "test")
        self.token = self.lock.acquire()
        self.targets = OrderedDict()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def source_rel(self, run, model, sid):
        return "thesis/results/intermediate/%s/%s/sources/%s/generated-code.hpp" % (run, model, sid)

    def add_target(self, model, run, samples=SAMPLES, salt=None):
        rows = []
        for bench, execution_model, index in samples:
            sid = sample_id(model, bench, execution_model, index)
            text = "// %s %s\nint f() { return %d; }\n" % (run, sid, index)
            if salt and sid in salt:
                text += "// %s\n" % salt[sid]
            relative = self.source_rel(run, model, sid)
            self.write(relative, text)
            rows.append(OrderedDict([
                ("schema_version", "assembly.v2"), ("run_id", run), ("model_id", model), ("sample_id", sid),
                ("execution_model", execution_model), ("benchmark", "%s/%s" % bench), ("assembled", True),
                ("source_path", relative), ("source_sha256", hashlib.sha256(text.encode("utf-8")).hexdigest()),
                ("drivers", OrderedDict([("benchmark_dir", "drivers/cpp/benchmarks/%s/%s" % bench),
                                         ("model_driver", "serial-driver.cc")]))]))
        self.write("thesis/results/intermediate/%s/%s/assembly.jsonl" % (run, model),
                   "".join(json.dumps(row) + "\n" for row in rows))
        facts, assembly = pt._samples(self.root, run, model)
        base = run == BASE
        self.targets[(model, run)] = pt._target(model, None if base else "static_feedback", 0 if base else 1, run,
                                                None if base else "full_ext_recovery_003",
                                                "base" if base else "continued", facts, assembly)
        return self

    def table(self):
        document = OrderedDict([("schema_version", pt.SCHEMA), ("run_id", pl.SUCCESSOR),
                                ("model_ids", list(pl.MODELS)), ("targets", list(self.targets.values()))])
        document["table_sha256"] = canonical_sha256(document)
        return pt.TargetTable(self.root, document)

    def path(self, target, name):
        return self.root / pt.ledger_relative(target.model_id, target.source_run, name)

    def rows(self, target, name=pt.ENHANCED_FILE):
        return [OrderedDict(r) for r in sw.read_jsonl(self.path(target, name))]

    def phase2_files(self):
        base = self.root / pl.RESULTS_REL
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file()) \
            if base.is_dir() else []


def native_main(root, config, run_id, model):
    """main()'s per-model body for a fresh model (no resume), restated 1:1
    from run_enhanced_tests.main lines 786-1198 (discovery, filter, specs,
    precompute_gates, per-execution-model process_sample)."""
    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    settings = stage_settings(config)
    run_timeout = float(stage.get("run_timeout_seconds", ret.DEFAULT_RUN_TIMEOUT))
    execution_models = list(settings["execution_models"])
    launch_settings = dict(settings["enhanced_launch"])
    mismatch_k = int(((config.get("stages") or {}).get("repair") or {})
                     .get("feedback", {}).get("mismatch_report_max_indices", 3))
    llm_specs = ret.load_llm_specs(Path(str(ret.DEFAULT_SPECS_PATH)))
    signatures = ret.load_serial_signatures()
    gate_cache, wrapper_cache = {}, {}
    counts = Counter()
    samples_seen = 0
    specs_by_benchmark = {}
    worklist = []
    for sample in framework.iter_assembled_samples(root, root / "thesis/results/intermediate", run_id, model):
        if sample.execution_model not in execution_models:
            continue
        benchmark = f"{sample.problem_type}/{sample.name}"
        cpu_cc = sample.benchmark_dir / "cpu.cc"
        if not cpu_cc.exists() or "ENHANCED_TEST_SIZE_DEFAULT" not in cpu_cc.read_text(encoding="utf-8"):
            counts["benchmark_not_parameterizable"] += 1
            continue
        samples_seen += 1
        if benchmark not in specs_by_benchmark:
            specs_by_benchmark[benchmark] = build_benchmark_specs(benchmark, llm_specs.get(benchmark, []), config)
        pending = list(specs_by_benchmark[benchmark])
        if pending:
            worklist.append((sample, benchmark, pending))
    ret.precompute_gates(worklist, gate_cache, wrapper_cache, signatures, mismatch_k)
    records, groups = [], []
    for execution_model in execution_models:
        for sample, benchmark, pending in [e for e in worklist if e[0].execution_model == execution_model]:
            found, rows = ret.process_sample(sample, benchmark, pending, gate_cache, run_id, model, mismatch_k,
                                             run_timeout, launch_settings)
            records.extend(found)
            groups.extend(rows)
    return records, groups, counts, samples_seen


class EnhancedCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(self._tmp.name)
        self.config = copy.deepcopy(CONFIG)
        self.logs = []

    def tearDown(self):
        self.repo.lock.release()
        self._tmp.cleanup()

    def run_enhanced(self, stubs=None, table=None, targets=None, authority=None, stop=None, config=None):
        table = table or self.repo.table()
        stubs = stubs or Stubs()
        with stubs.installed():
            return me.run_enhanced(self.repo.root, config or self.config, table,
                                   authority or FakeAuthority(self.repo.token),
                                   table.targets if targets is None else targets,
                                   log=self.logs.append, stop=stop)

    def expected(self, target, config=None):
        llm_specs = ret.load_llm_specs(Path(str(ret.DEFAULT_SPECS_PATH)))
        return pg.expected_enhanced(self.repo.root, config or self.config, target, llm_specs, {})

    def assert_complete(self, target):
        """Ledger holds exactly the expected (sample, spec) pairs once."""
        rows = self.repo.rows(target)
        pairs = [(r["sample_id"], key_of(r["spec"])) for r in rows]
        self.assertEqual(len(pairs), len(set(pairs)))
        expected = self.expected(target)
        self.assertEqual(sorted(pairs), sorted((sid, key) for sid, keys in expected.items() for key in keys))
        self.assertEqual(pg.missing_enhanced(self.repo.root, self.config, target,
                                             ret.load_llm_specs(Path(str(ret.DEFAULT_SPECS_PATH))), {}), {})
        return rows


class TestRecordEquivalence(EnhancedCase):
    def test_rows_equal_native_process_sample_usage(self):
        self.repo.add_target(MODEL_A, BASE)
        table = self.repo.table()
        target = table.targets[0]
        totals = self.run_enhanced(table=table)
        rows = self.assert_complete(target)
        groups = self.repo.rows(target, pt.ENHANCED_GROUPS_FILE)
        with Stubs().installed():
            records, native_groups, counts, seen = native_main(self.repo.root, self.config, BASE, MODEL_A)
        ours = OrderedDict(((r["sample_id"], key_of(r["spec"])), strip(r)) for r in rows)
        native = OrderedDict(((r["sample_id"], key_of(r["spec"])), strip(normalized(r))) for r in records)
        self.assertEqual(set(ours), set(native))
        for key, record in native.items():
            self.assertEqual(ours[key], record)
            self.assertEqual(list(ours[key]), list(record))  # native field order
        self.assertEqual(sorted(json.dumps(strip(g, PHASE2_FIELDS)) for g in groups),
                         sorted(json.dumps(normalized(g)) for g in native_groups))
        # phase-2 provenance on every row, binding on records only
        for row in rows:
            for field, value in pt.provenance(target, row["sample_id"]).items():
                self.assertEqual(row[field], value)
            self.assertEqual(row["phase2_binding"], BINDING)
            self.assertEqual(row["run_id"], BASE)
        for row in groups:
            self.assertNotIn("phase2_binding", row)
            self.assertEqual(row["candidate_source_sha256"], target.samples[row["sample_id"]]["source_sha256"])
        # spec set == ledger.expected_enhanced, 20 per parameterizable sample
        expected = self.expected(target)
        self.assertEqual(sorted(expected), sorted(sample_id(MODEL_A, b, e, i) for b, e, i in SAMPLES if b != GEMM))
        self.assertTrue(all(len(keys) == 20 for keys in expected.values()))
        self.assertEqual(totals["rows"], 80)
        self.assertEqual((totals["benchmark_not_parameterizable"], counts["benchmark_not_parameterizable"]), (1, 1))
        self.assertEqual(seen, 4)
        # the stubs exercise every native record path
        statuses = set(r["status"] for r in rows)
        self.assertTrue({"pass", "fail", "crash", "timeout", "runtime_error", "build_failed",
                         "baseline_incompatible", "numerically_unstable"} <= statuses, statuses)
        self.assertTrue(any(r.get("mismatches") for r in rows))
        self.assertTrue(any(r.get("baseline_gate") == "non_finite_reference" for r in rows))


class TestSharedGateCache(EnhancedCase):
    def test_each_spec_key_gated_once_per_invocation(self):
        for model in (MODEL_A, MODEL_B):
            for run in (BASE, CAND):
                self.repo.add_target(model, run)
        table = self.repo.table()
        stubs = Stubs()
        authority = FakeAuthority(self.repo.token)
        totals = self.run_enhanced(stubs=stubs, table=table, authority=authority)
        keys = set()
        for target in table.targets:
            self.assert_complete(target)
            for specs in self.expected(target).values():
                keys.update(specs)
        self.assertEqual(len(keys), 40)
        self.assertEqual(set(stubs.gated), keys)
        self.assertEqual(set(stubs.gated.values()), {1})
        self.assertEqual(totals["gates_computed"], 40)
        self.assertEqual(stubs.wrappers, Counter({LU[1]: 1, AXPY[1]: 1}))
        self.assertEqual(totals["rows"], 4 * 80)
        # check per target (never per sample), enforce once per model
        self.assertEqual(authority.checks, 4)
        self.assertEqual(authority.enforced, [("enhanced", MODEL_A), ("enhanced", MODEL_B)])


class TestRegistrationAndResume(EnhancedCase):
    def crash(self):
        """A run that dies inside run_binary of the mpi sample (serial and omp
        samples already complete), then a torn half-line as if the process
        had died during an append."""
        self.repo.add_target(MODEL_A, BASE)
        target = self.repo.table().targets[0]
        failing = sample_id(MODEL_A, AXPY, "mpi", 0)
        with self.assertRaises(pl.GlobalStop) as caught:
            self.run_enhanced(stubs=Stubs(fail_on=(failing, 2)))
        self.assertIn("worker failed", str(caught.exception))
        rows = self.repo.rows(target)
        self.assertEqual(len(rows), 60)
        self.assertNotIn(failing, set(r["sample_id"] for r in rows))
        self.assertFalse(self.repo.path(target, pt.ENHANCED_SUMMARY_FILE).exists())
        return target, failing

    def test_registration_written_before_first_record(self):
        self.repo.add_target(MODEL_A, BASE)
        target = self.repo.table().targets[0]
        registration = self.repo.path(target, pt.ENHANCED_REGISTRATION_FILE)
        observed = []
        real = sw.durable_append_jsonl

        def spy(path, row):
            observed.append(registration.is_file())
            return real(path, row)

        with mock.patch.object(sw, "durable_append_jsonl", spy):
            self.run_enhanced()
        self.assertTrue(observed and all(observed))
        document = json.loads(registration.read_text(encoding="utf-8"))
        self.assertEqual((document["run_id"], document["target_id"], document["candidate_source_run"]),
                         (pl.SUCCESSOR, target.target_id, BASE))
        model = document["enhanced_model_execution_provenance"]
        self.assertEqual(model["candidate_sample_count"], 5)
        self.assertEqual(model["global_execution_fingerprint_sha256"],
                         document["enhanced_execution_provenance"]["enhanced_execution_fingerprint_sha256"])
        self.assertEqual([s["source_sha256"] for s in model["candidate_sources"]["samples"]],
                         [target.samples[sid]["source_sha256"] for sid in sorted(target.samples)])
        self.assertFalse(registration.with_name(registration.name + ".tmp").exists())

    def test_crash_torn_tail_resume_completes_without_duplicates(self):
        target, failing = self.crash()
        ledger = self.repo.path(target, pt.ENHANCED_FILE)
        registration = self.repo.path(target, pt.ENHANCED_REGISTRATION_FILE).read_bytes()
        with ledger.open("ab") as handle:
            handle.write(b'{"schema_version": "enhanced_tests.v1", "sample_id": "tor')
        stubs = Stubs()
        totals = self.run_enhanced(stubs=stubs)
        rows = self.assert_complete(target)
        self.assertEqual(len(rows), 80)
        self.assertEqual(totals["rows"], 20)
        self.assertEqual(set(stubs.runs), {failing})  # only the missing sample ran
        self.assertEqual(set(r["sample_id"] for r in rows[60:]), {failing})
        torn = ledger.with_name(ledger.name + ".torn").read_text(encoding="utf-8")
        self.assertIn('\\"sample_id\\": \\"tor', torn)
        self.assertEqual(self.repo.path(target, pt.ENHANCED_REGISTRATION_FILE).read_bytes(), registration)
        summary = json.loads(self.repo.path(target, pt.ENHANCED_SUMMARY_FILE).read_text(encoding="utf-8"))
        self.assertEqual(summary["resumed_rows"], 60)
        self.assertEqual(sum(v for k, v in summary["counts"].items() if k != "benchmark_not_parameterizable"), 20)

    def test_changed_condition_refuses_resume(self):
        target, _ = self.crash()
        before = self.repo.path(target, pt.ENHANCED_FILE).read_bytes()
        config = copy.deepcopy(self.config)
        config["stages"]["enhanced_tests"]["run_timeout_seconds"] = 61
        with self.assertRaises(pl.GlobalStop) as caught:
            self.run_enhanced(config=config)
        self.assertIn("global execution condition", str(caught.exception))
        self.assertEqual(self.repo.path(target, pt.ENHANCED_FILE).read_bytes(), before)

    def test_changed_candidate_source_refuses_resume(self):
        target, failing = self.crash()
        before = self.repo.path(target, pt.ENHANCED_FILE).read_bytes()
        # the candidate is swapped and a new table is frozen around it
        self.repo.add_target(MODEL_A, BASE, salt={failing: "a different program"})
        with self.assertRaises(pl.GlobalStop) as caught:
            self.run_enhanced()
        self.assertIn("candidate source contents", str(caught.exception))
        self.assertEqual(self.repo.path(target, pt.ENHANCED_FILE).read_bytes(), before)

    def test_rows_without_registration_refuse(self):
        target, _ = self.crash()
        self.repo.path(target, pt.ENHANCED_REGISTRATION_FILE).unlink()
        with self.assertRaises(pl.GlobalStop) as caught:
            self.run_enhanced()
        self.assertIn("without a registration", str(caught.exception))
        self.assertFalse(self.repo.path(target, pt.ENHANCED_REGISTRATION_FILE).exists())

    def test_complete_target_is_not_remeasured(self):
        self.repo.add_target(MODEL_A, BASE)
        target = self.repo.table().targets[0]
        self.run_enhanced()
        ledger = self.repo.path(target, pt.ENHANCED_FILE).read_bytes()
        summary = self.repo.path(target, pt.ENHANCED_SUMMARY_FILE).read_bytes()
        stubs = Stubs()
        totals = self.run_enhanced(stubs=stubs)
        self.assertEqual((totals["rows"], totals["gates_computed"], totals["targets_complete"]), (0, 0, 1))
        self.assertEqual(sum(stubs.runs.values()), 0)
        self.assertEqual(self.repo.path(target, pt.ENHANCED_FILE).read_bytes(), ledger)
        self.assertEqual(self.repo.path(target, pt.ENHANCED_SUMMARY_FILE).read_bytes(), summary)


class TestJobs(EnhancedCase):
    def pools(self, config=None):
        created = []

        class Recording(ThreadPoolExecutor):
            def __init__(self, max_workers=None, *args, **kwargs):
                created.append(max_workers)
                super().__init__(max_workers, *args, **kwargs)

        with mock.patch.object(me, "ThreadPoolExecutor", Recording), \
                mock.patch.object(sys, "argv", ["run.py", "--jobs", "7"]):
            self.run_enhanced(config=config)
        return created

    def test_pool_sizes_are_the_config_jobs(self):
        self.assertNotIn("jobs", inspect.signature(me.run_enhanced).parameters)
        self.repo.add_target(MODEL_A, BASE)
        self.assertEqual(self.pools(), [2, 1, 1])  # serial, omp, mpi of the frozen config

    def test_changed_config_jobs_are_used_and_fingerprinted(self):
        self.repo.add_target(MODEL_A, BASE)
        target = self.repo.table().targets[0]
        config = copy.deepcopy(self.config)
        config["stages"]["enhanced_tests"]["jobs"] = {"serial": 3, "omp": 2, "mpi": 4}
        self.assertEqual(self.pools(config), [3, 2, 4])
        registration = json.loads(self.repo.path(target, pt.ENHANCED_REGISTRATION_FILE).read_text(encoding="utf-8"))
        effective = registration["enhanced_execution_provenance"]["components"]["G_effective_config"]
        self.assertEqual(effective["effective_jobs"], {"mpi": 4, "omp": 2, "serial": 3})
        self.assertEqual(registration["effective_config"]["jobs"], {"serial": 3, "omp": 2, "mpi": 4})


class TestStop(EnhancedCase):
    def test_stop_cancels_queued_samples_cleanly(self):
        self.repo.add_target(MODEL_A, BASE, samples=SERIAL_ONLY)
        target = self.repo.table().targets[0]
        real = ret.process_sample
        calls = []
        lock = threading.Lock()

        def slow_after_first(*args):
            with lock:
                calls.append(args[0].sample_id)
                first = len(calls) == 1
            if not first:
                threading.Event().wait(2.0)  # still running when stop() fires
            return real(*args)

        # stop is requested as soon as the first sample's rows are on disk
        ledger = self.repo.path(target, pt.ENHANCED_FILE)
        with mock.patch.object(ret, "process_sample", slow_after_first):
            totals = self.run_enhanced(stop=ledger.exists)
        rows = self.repo.rows(target)
        self.assertEqual(totals["stopped"], 1)
        self.assertEqual(totals["samples"], 1)
        self.assertEqual(len(calls), 3)  # the 4th sample was cancelled before it started
        self.assertEqual(set(r["sample_id"] for r in rows), {calls[0]})
        self.assertEqual(len(rows), 20)
        self.assertFalse(self.repo.path(target, pt.ENHANCED_SUMMARY_FILE).exists())
        totals = self.run_enhanced()
        self.assert_complete(target)
        self.assertEqual(totals["rows"], 60)

    def test_stop_before_any_target_writes_nothing(self):
        self.repo.add_target(MODEL_A, BASE)
        totals = self.run_enhanced(stop=lambda: True)
        self.assertEqual(totals["stopped"], 1)
        self.assertEqual(self.repo.phase2_files(), [])


class TestRefusals(EnhancedCase):
    def test_wrong_token_refuses_before_writing(self):
        self.repo.add_target(MODEL_A, BASE)
        with self.assertRaises(RecoveryRefused):
            self.run_enhanced(authority=FakeAuthority("0" * 32))
        self.assertEqual(self.repo.phase2_files(), [])

    def test_source_drift_before_the_target_refuses(self):
        self.repo.add_target(MODEL_A, BASE)
        table = self.repo.table()
        sid = sample_id(MODEL_A, LU, "serial", 0)
        self.repo.write(self.repo.source_rel(BASE, MODEL_A, sid), "// drifted\n")
        with self.assertRaises(pl.GlobalStop):
            self.run_enhanced(table=table)
        self.assertEqual(self.repo.phase2_files(), [])

    def test_source_drift_during_measurement_refuses_its_rows(self):
        self.repo.add_target(MODEL_A, BASE)
        target = self.repo.table().targets[0]
        victim = sample_id(MODEL_A, AXPY, "mpi", 0)

        def drift(built):
            if built["sample_id"] == victim:
                self.repo.write(self.repo.source_rel(BASE, MODEL_A, victim), "// swapped while measured\n")

        with self.assertRaises(pl.GlobalStop) as caught:
            self.run_enhanced(stubs=Stubs(on_run=drift))
        self.assertIn("changed during the enhanced measurement", str(caught.exception))
        rows = self.repo.rows(target)
        self.assertNotIn(victim, set(r["sample_id"] for r in rows))
        self.assertNotIn(victim, set(r["sample_id"] for r in self.repo.rows(target, pt.ENHANCED_GROUPS_FILE)))
        self.assertEqual(len(rows), 60)

    def test_foreign_target_refuses(self):
        self.repo.add_target(MODEL_A, BASE)
        table = self.repo.table()
        other = Repo(tempfile.mkdtemp(dir=self._tmp.name)).add_target(MODEL_B, BASE)
        foreign = pt.Target(other.targets[(MODEL_B, BASE)])
        with self.assertRaises(pl.GlobalStop):
            self.run_enhanced(table=table, targets=[foreign])
        self.assertEqual(self.repo.phase2_files(), [])
        other.lock.release()

    def test_policy_and_toolchain_gates_are_environment_errors(self):
        self.repo.add_target(MODEL_A, BASE)
        authority = FakeAuthority(self.repo.token)

        def stale():
            raise capabilities.EnhancedPolicyError("stale policy")

        with mock.patch.object(capabilities, "policy_preflight", stale):
            with self.assertRaises(EnvironmentError):
                self.run_enhanced(authority=authority)
        stubs = Stubs()
        with stubs.installed(), mock.patch.object(ret, "missing_toolchain",
                                                  lambda models, primary_compiler="g++": ["mpicxx (mpi builds)"]):
            with self.assertRaises(EnvironmentError):
                me.run_enhanced(self.repo.root, self.config, self.repo.table(), authority,
                                self.repo.table().targets, log=self.logs.append)
        self.assertEqual(authority.checks, 0)
        self.assertEqual(self.repo.phase2_files(), [])


class TestSummary(EnhancedCase):
    def test_summary_native_shaped_and_consistent_with_ledger(self):
        self.repo.add_target(MODEL_A, BASE).add_target(MODEL_A, CAND)
        table = self.repo.table()
        self.run_enhanced(table=table)
        settings = stage_settings(self.config)
        for target in table.targets:
            rows = self.assert_complete(target)
            summary = json.loads(self.repo.path(target, pt.ENHANCED_SUMMARY_FILE).read_text(encoding="utf-8"),
                                 object_pairs_hook=OrderedDict)
            registration = json.loads(self.repo.path(target, pt.ENHANCED_REGISTRATION_FILE)
                                      .read_text(encoding="utf-8"))
            self.assertEqual(list(summary)[:len(NATIVE_SUMMARY_KEYS)], NATIVE_SUMMARY_KEYS)
            self.assertEqual(summary["schema_version"], "enhanced_tests.v1.summary")
            self.assertEqual((summary["run_id"], summary["model_id"]), (target.source_run, MODEL_A))
            counts = Counter(summary["counts"])
            self.assertEqual(counts.pop("benchmark_not_parameterizable"), 1)
            self.assertEqual(counts, Counter(r["status"] for r in rows))
            self.assertEqual(sum(counts.values()) + summary["resumed_rows"], len(rows))
            self.assertEqual((summary["samples_seen"], summary["legacy_mixed_rows"]), (4, 0))
            self.assertEqual(summary["timing_semantics"], ret.TIMING_SEMANTICS)
            self.assertEqual(summary["build_groups_file"], pt.ENHANCED_GROUPS_FILE)
            effective = dict(settings)
            effective.update({"jobs": {"serial": 2, "omp": 1, "mpi": 1}, "run_timeout_seconds": 60.0,
                              "specs_file": str(ret.DEFAULT_SPECS_PATH)})
            self.assertEqual(summary["effective_config"], normalized(effective))
            self.assertEqual(summary["enhanced_model_execution_provenance"],
                             registration["enhanced_model_execution_provenance"])
            self.assertEqual(summary["enhanced_execution_provenance"]["components"]["A_spec_set"]["specs_sha256"],
                             hashlib.sha256(ret.DEFAULT_SPECS_PATH.read_bytes()).hexdigest())
            self.assertEqual((summary["writer_run_id"], summary["candidate_source_run"], summary["variant"],
                              summary["iteration"]), (pl.SUCCESSOR, target.source_run, target.variant,
                                                      target.iteration))
            self.assertEqual(summary["phase2_binding"], BINDING)

    def test_expected_totals(self):
        self.repo.add_target(MODEL_A, BASE).add_target(MODEL_B, CAND)
        llm_specs = ret.load_llm_specs(Path(str(ret.DEFAULT_SPECS_PATH)))
        self.assertEqual(me.expected_totals(self.repo.root, self.config, self.repo.table(), llm_specs), (8, 160))
        self.assertEqual(me.expected_totals(self.repo.root, self.config, self.repo.table()), (8, 160))


if __name__ == "__main__":
    unittest.main()
