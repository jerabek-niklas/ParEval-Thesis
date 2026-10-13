"""Tests of the phase-2 verifier (verify.py) and the unified reader
(composite.py) on a synthetic repository in a temp dir: a tiny pilot block
(base + one repair iteration) and a tiny full_ext block (base target, one
static_feedback and one test_feedback candidate target) with complete
phase-2 ledgers. The expensive shared inputs (immutability, population, run
binding) are injected; enhanced specs and fingerprints are the real ones
(cheap on the fixture).

    python3 -B -m unittest -v thesis.recovery_successor_005.test_verify
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import types
import unittest
from collections import OrderedDict
from pathlib import Path

from thesis.config.load_config import load_config
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt
from thesis.recovery_successor_005 import verify as pv

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = load_config(REPO_ROOT / pl.CONFIG_REL)
MODEL = "claude_fable_5"
PILOT_BENCH = "scan/30_scan_prefix_sum"
FULL_BENCH = "dense_la/03_dense_la_axpy"
PILOT_ITER = "pilot_002__test_feedback__iter1"
STATIC_RUN = "full_ext_recovery_001__static_feedback__iter1"
TEST_RUN = "full_ext_recovery_001__test_feedback__iter1"
GLOBAL_SHA = "a" * 64
CONTRACT = "c" * 64
AUTHORIZATION = "d" * 64


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeAuthority:
    """Same interface as the lead's Phase2Authority."""
    token = "token"

    def check(self):
        return True

    def enforce(self, stage, model):
        return OrderedDict([("stage_runtime_sha256", sha("runtime:" + stage)),
                            ("invocation_sha256", sha("invocation:%s:%s" % (stage, model))),
                            ("contract_sha256", CONTRACT), ("authorization_sha256", AUTHORIZATION)])

    def binding(self, stage, model):
        result = self.enforce(stage, model)
        return OrderedDict((k, result[k]) for k in pv.BINDING_FIELDS)


EXPECTED_BINDING = OrderedDict([
    ("contract_sha256", CONTRACT), ("authorization_sha256", AUTHORIZATION),
    ("stage_runtime_sha256", OrderedDict((s, [sha("runtime:" + s)]) for s in pl.STAGES)),
    ("invocation_sha256", OrderedDict((s, [sha("invocation:%s:%s" % (s, MODEL))]) for s in pl.STAGES)),
])


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def read_jsonl(path):
    return [json.loads(line, object_pairs_hook=OrderedDict)
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def edit_jsonl(path, function):
    write_jsonl(path, function(read_jsonl(path)))


class Repo:
    """The synthetic repository (complete: every check passes)."""

    def __init__(self, root):
        from thesis.enhanced_tests.specs import build_benchmark_specs

        self.root = Path(root)
        self.authority = FakeAuthority()
        self.static_settings = pg.static_settings(CONFIG)
        self.dynamic_settings = pg.dynamic_settings(CONFIG)
        self.specs = OrderedDict((b, build_benchmark_specs(b, [], CONFIG)) for b in (PILOT_BENCH, FULL_BENCH))
        for benchmark in self.specs:
            cpu = self.root / "drivers/cpp/benchmarks" / benchmark / "cpu.cc"
            cpu.parent.mkdir(parents=True, exist_ok=True)
            cpu.write_text("#define ENHANCED_TEST_SIZE_DEFAULT 1024\n", encoding="utf-8")
        # pilot block: static records omit inapplicable tools (as the real pilot does)
        self.pilot = OrderedDict([
            (pl.PILOT, self.assembly(pl.PILOT, [(PILOT_BENCH, "serial"), (PILOT_BENCH, "omp")])),
            (PILOT_ITER, self.assembly(PILOT_ITER, [(PILOT_BENCH, "omp")]))])
        for run, samples in self.pilot.items():
            self.write_static(run, samples, applicable_only=True)
            self.write_records(run, samples)
            write_jsonl(self.run_path(run, pt.ENHANCED_FILE),
                        [self.enhanced_row(run, s, spec) for s in samples for spec in self.specs[s["benchmark"]]])
        # full_ext block
        base = self.assembly(pl.PARENT, [(FULL_BENCH, "serial"), (FULL_BENCH, "mpi")])
        static_target = self.assembly(STATIC_RUN, [(FULL_BENCH, "serial")])
        test_target = self.assembly(TEST_RUN, [(FULL_BENCH, "omp")])
        self.write_static(pl.PARENT, base)
        self.write_static(STATIC_RUN, static_target)
        self.write_static(TEST_RUN, test_target, skip=pl.EXTERNAL_TOOLS)
        self.write_records(pl.PARENT, base)
        self.write_records(TEST_RUN, test_target)
        self.table = pt.TargetTable(self.root, self.table_document([
            (None, 0, pl.PARENT, None, base),
            ("static_feedback", 1, STATIC_RUN, pl.ORIGIN, static_target),
            ("test_feedback", 1, TEST_RUN, pl.ORIGIN, test_target)]))
        self.lineage = types.SimpleNamespace(sha256="e" * 64, targets_sha256=self.table.sha256,
                                             verify=lambda: OrderedDict([(pl.PILOT, 1)]))
        # phase-2 ledgers
        test = self.table.get("%s/%s" % (MODEL, TEST_RUN))
        for tool in pl.EXTERNAL_TOOLS:
            write_jsonl(self.ledger(TEST_RUN, "static.%s.jsonl" % tool),
                        [self.supplement_row(test, sid, tool) for sid in test.samples])
        static = self.table.get("%s/%s" % (MODEL, STATIC_RUN))
        for stage, name, record in (("correctness", pt.CORRECTNESS_FILE, self.correctness_record),
                                    ("dynamic", pt.DYNAMIC_FILE, self.dynamic_record)):
            rows = []
            for sid, facts in static.samples.items():
                row = record(STATIC_RUN, facts)
                row.update(pt.provenance(static, sid))
                row["phase2_binding"] = self.authority.binding(stage, MODEL)
                rows.append(row)
            write_jsonl(self.ledger(STATIC_RUN, name), rows)
        for target in self.table.targets:
            rows, groups = [], []
            for sid, facts in target.samples.items():
                for spec in self.specs[facts["benchmark"]]:
                    row = self.enhanced_row(target.source_run, facts, spec)
                    row.update(pt.provenance(target, sid))
                    row["phase2_binding"] = self.authority.binding("enhanced", MODEL)
                    rows.append(row)
                group = OrderedDict([("sample_id", sid), ("execution_model", facts["execution_model"]),
                                     ("size", 0), ("spec_count", 20), ("build_status", "success")])
                group.update(pt.provenance(target, sid))
                groups.append(group)
            write_jsonl(self.ledger(target.source_run, pt.ENHANCED_FILE), rows)
            write_jsonl(self.ledger(target.source_run, pt.ENHANCED_GROUPS_FILE), groups)
            self.register(target)

    # -- builders ------------------------------------------------------------------
    def run_path(self, run, name):
        return self.root / pt.run_dir(run, MODEL) / name

    def ledger(self, run, name):
        return self.root / pt.ledger_relative(MODEL, run, name)

    def assembly(self, run, cells):
        rows, facts = [], []
        for benchmark, execution_model in cells:
            kind, name = benchmark.split("/")
            sample_id = "%s__%s__%s__%s__sample_0" % (MODEL, kind, name, execution_model)
            source_rel = "%s/sources/%s/generated-code.hpp" % (pt.run_dir(run, MODEL), sample_id)
            data = ("// %s %s\nint f() { return 0; }\n" % (run, sample_id)).encode("utf-8")
            (self.root / source_rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / source_rel).write_bytes(data)
            source_sha = hashlib.sha256(data).hexdigest()
            rows.append(OrderedDict([
                ("schema_version", "assembly.v2"), ("run_id", run), ("model_id", MODEL),
                ("sample_id", sample_id), ("execution_model", execution_model), ("benchmark", benchmark),
                ("assembled", True), ("source_path", source_rel), ("source_sha256", source_sha),
                ("drivers", OrderedDict([("benchmark_dir", "drivers/cpp/benchmarks/" + benchmark),
                                         ("model_driver", "drivers/cpp/models/%s-driver.cc" % execution_model)]))]))
            facts.append(OrderedDict([("sample_id", sample_id), ("execution_model", execution_model),
                                      ("benchmark", benchmark), ("source_sha256", source_sha),
                                      ("source_path", source_rel)]))
        write_jsonl(self.run_path(run, "assembly.jsonl"), rows)
        return facts

    def tool_entry(self, tool, execution_model, source_sha=None, state="COMPLETED"):
        from thesis.evaluation import framework
        from thesis.evaluation import run_static_analysis as rsa

        if not self.static_settings[tool].applies_to(execution_model):
            return rsa.not_applicable_entry(tool, execution_model)
        entry = framework.ToolResult(tool=tool, ran=True, exit_code=0, duration_seconds=0.5,
                                     analysis_state=state).to_dict()
        entry["num_low_confidence"] = 0
        if source_sha is not None:
            condition = OrderedDict([("tool", tool), ("sample_source_sha256", source_sha),
                                     ("build", OrderedDict([("execution_model", execution_model)]))])
            entry["tool_execution_condition"] = condition
            entry["tool_execution_fingerprint_sha256"] = canonical_sha256(condition)
        return entry

    def write_static(self, run, samples, applicable_only=False, skip=()):
        rows = []
        for facts in samples:
            tools = OrderedDict()
            for tool, settings in self.static_settings.items():
                if tool in skip or (applicable_only and not settings.applies_to(facts["execution_model"])):
                    continue
                tools[tool] = self.tool_entry(tool, facts["execution_model"], facts["source_sha256"])
            rows.append(OrderedDict([
                ("schema_version", "static_analysis.v2"), ("run_id", run), ("model_id", MODEL),
                ("sample_id", facts["sample_id"]), ("execution_model", facts["execution_model"]),
                ("sample_source_sha256", facts["source_sha256"]), ("tools", tools)]))
        write_jsonl(self.run_path(run, pt.STATIC_FILE), rows)

    def correctness_record(self, run, facts, verdict="pass"):
        return OrderedDict([("schema_version", "correctness.v1"), ("run_id", run), ("model_id", MODEL),
                            ("sample_id", facts["sample_id"]), ("execution_model", facts["execution_model"]),
                            ("verdict", verdict)])

    def dynamic_record(self, run, facts):
        tools = OrderedDict()
        for tool, settings in self.dynamic_settings.items():
            applies = settings.applies_to(facts["execution_model"])
            tools[tool] = OrderedDict([("tool", tool), ("ran", applies),
                                       ("analysis_state", "COMPLETED" if applies else "NOT_APPLICABLE")])
        return OrderedDict([("schema_version", "dynamic_analysis.v1"), ("run_id", run), ("model_id", MODEL),
                            ("sample_id", facts["sample_id"]), ("execution_model", facts["execution_model"]),
                            ("tools", tools)])

    def write_records(self, run, samples):
        write_jsonl(self.run_path(run, pt.CORRECTNESS_FILE), [self.correctness_record(run, s) for s in samples])
        write_jsonl(self.run_path(run, pt.DYNAMIC_FILE), [self.dynamic_record(run, s) for s in samples])

    def enhanced_row(self, run, facts, spec, status="pass"):
        return OrderedDict([("schema_version", "enhanced_tests.v1"), ("run_id", run), ("model_id", MODEL),
                            ("sample_id", facts["sample_id"]), ("execution_model", facts["execution_model"]),
                            ("benchmark", facts["benchmark"]), ("spec", spec), ("status", status)])

    def supplement_row(self, target, sample_id, tool):
        from thesis.evaluation import successor_supplement as ss

        facts = target.samples[sample_id]
        binding = self.authority.binding("static.%s" % tool, MODEL)
        row = OrderedDict([
            ("schema_version", ss.SUPPLEMENT_SCHEMA), ("run_id", pl.SUCCESSOR),
            ("authority_run_id", pl.SUCCESSOR), ("candidate_source_run", target.source_run),
            ("model_id", MODEL), ("variant", target.variant), ("iteration", target.iteration),
            ("sample_id", sample_id), ("execution_model", facts["execution_model"]), ("tool", tool),
            ("candidate_source_sha256", facts["source_sha256"]),
            ("entry", self.tool_entry(tool, facts["execution_model"], facts["source_sha256"]))])
        row.update(binding)
        return row

    def table_document(self, specs):
        targets = []
        for variant, iteration, run, owner, samples in specs:
            relative = pt.run_dir(run, MODEL) + "/assembly.jsonl"
            targets.append(OrderedDict([
                ("target_id", "%s/%s" % (MODEL, run)), ("model_id", MODEL), ("block", "full_ext"),
                ("variant", variant), ("iteration", iteration), ("source_run", run), ("loop_owner", owner),
                ("loop_kind", "base" if iteration == 0 else "native"),
                ("assembly", OrderedDict([("path", relative), ("raw_sha256", hashlib.sha256(
                    (self.root / relative).read_bytes()).hexdigest())])),
                ("sample_count", len(samples)), ("samples", samples)]))
        document = OrderedDict([
            ("schema_version", pt.SCHEMA), ("run_id", pl.SUCCESSOR), ("model_ids", list(pl.MODELS)),
            ("excluded_historical_runs", list(pl.EXCLUDED_HISTORICAL_RUNS)), ("census_digest", "0" * 64),
            ("census_summary", OrderedDict()), ("target_count", len(targets)),
            ("sample_totals", OrderedDict()), ("targets", targets)])
        document["table_sha256"] = canonical_sha256(document)
        return document

    def register(self, target):
        from thesis.enhanced_tests import execution_provenance as ep

        global_fingerprint = OrderedDict([("enhanced_execution_fingerprint_sha256", GLOBAL_SHA)])
        candidate = ep.candidate_source_fingerprint(self.root / pt.INTERMEDIATE_REL, target.source_run,
                                                    MODEL, self.root)
        # the identity fields and provenance keys measure_enhanced writes
        document = OrderedDict([
            ("schema_version", "phase2_enhanced_registration.v1"), ("run_id", pl.SUCCESSOR),
            ("target_id", target.target_id), ("model_id", MODEL), ("candidate_source_run", target.source_run),
            ("variant", target.variant), ("iteration", target.iteration),
            ("enhanced_execution_provenance", global_fingerprint),
            ("enhanced_model_execution_provenance", ep.model_execution_fingerprint(global_fingerprint, candidate))])
        self.ledger(target.source_run, pt.ENHANCED_REGISTRATION_FILE).write_text(
            json.dumps(document, indent=2), encoding="utf-8")

    def deep(self, **overrides):
        deep = OrderedDict([
            ("immutability", OrderedDict([("status", pv.PASS), ("detail", "injected")])),
            ("population", OrderedDict([("status", pv.PASS), ("detail", "injected")])),
            ("binding", copy.deepcopy(EXPECTED_BINDING)), ("llm_specs", {})])
        deep.update(overrides)
        return deep

    def verify(self, **overrides):
        return pv.verify_model(self.root, CONFIG, self.table, MODEL, self.lineage, self.deep(**overrides))


def failing(result):
    return sorted(c["check"] for c in result["checks"] if c["status"] != pv.PASS)


def check(result, name):
    return [c for c in result["checks"] if c["check"] == name][0]


class SyntheticRepoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="phase2_verify_")
        self.repo = Repo(self._tmp)
        self.root = self.repo.root

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)


class VerifyTest(SyntheticRepoTest):
    def test_complete_model_passes(self):
        result = self.repo.verify()
        self.assertEqual(failing(result), [])
        self.assertEqual(result["status"], pv.PASS)
        self.assertTrue(result["model_complete"])
        names = set(c["check"] for c in result["checks"])
        for run in (pl.PILOT, PILOT_ITER):
            for suffix in ("assembly", "static_coverage", "correctness_coverage", "dynamic_coverage",
                           "enhanced_pairs"):
                self.assertIn("pilot:%s:%s" % (run, suffix), names)
        for run in (pl.PARENT, STATIC_RUN, TEST_RUN):
            for suffix in ("plan_complete", "static_coverage", "static_supplement_entries",
                           "correctness_coverage", "dynamic_coverage", "enhanced_pairs",
                           "enhanced_registration", "phase2_provenance", "phase2_binding"):
                self.assertIn("full_ext:%s:%s" % (run, suffix), names)
        counts = result["counts"]
        self.assertEqual(counts["pilot"]["samples"], 3)
        self.assertEqual(counts["pilot"]["enhanced"]["rows"], 60)
        self.assertEqual(counts["full_ext"]["samples"], 4)
        self.assertEqual(counts["full_ext"]["correctness"], OrderedDict([
            ("historical", 3), ("phase2", 1), ("verdicts", OrderedDict([("pass", 4)]))]))
        self.assertEqual(counts["full_ext"]["dynamic"]["phase2"], 1)
        self.assertEqual(counts["full_ext"]["static"]["entries_by_source"],
                         OrderedDict([("historical_record", 26), ("phase2_supplement", 2)]))
        self.assertEqual(counts["full_ext"]["enhanced"]["expected_pairs"], 80)
        self.assertEqual(counts["full_ext"]["enhanced"]["specs_per_sample"], OrderedDict([("20", 4)]))
        self.assertEqual(counts["full_ext"]["enhanced"]["registrations"], 3)
        # deterministic (no timestamps in the report body)
        self.assertEqual(json.dumps(result), json.dumps(self.repo.verify()))

    def test_documented_gap_states_do_not_fail(self):
        def gaps(rows):
            for row in rows:
                if row["execution_model"] == "serial":
                    row["tools"]["infer"]["analysis_state"] = "TIMEOUT"
                    row["tools"]["gcc_analyzer"]["analysis_state"] = "TOOL_ERROR"
            return rows

        edit_jsonl(self.repo.run_path(pl.PARENT, pt.STATIC_FILE), gaps)
        edit_jsonl(self.repo.run_path(pl.PILOT, pt.STATIC_FILE), gaps)
        edit_jsonl(self.repo.run_path(pl.PILOT, pt.CORRECTNESS_FILE),
                   lambda rows: [OrderedDict(r, verdict="timeout") for r in rows])
        edit_jsonl(self.repo.ledger(STATIC_RUN, pt.CORRECTNESS_FILE),
                   lambda rows: [OrderedDict(r, verdict="build_failed") for r in rows])

        def dynamic_gap(rows):
            rows[0]["tools"]["asan_ubsan"]["analysis_state"] = "TOOL_ERROR"
            return rows

        edit_jsonl(self.repo.run_path(pl.PARENT, pt.DYNAMIC_FILE), dynamic_gap)
        statuses = ["timeout", "baseline_incompatible", "build_failed", "numerically_unstable"]
        edit_jsonl(self.repo.ledger(pl.PARENT, pt.ENHANCED_FILE), lambda rows: [
            OrderedDict(r, status=statuses[i % len(statuses)]) for i, r in enumerate(rows)])
        result = self.repo.verify()
        self.assertEqual(failing(result), [])
        self.assertTrue(result["model_complete"])
        full = result["counts"]["full_ext"]
        self.assertEqual(full["static"]["states"]["infer"]["TIMEOUT"], 1)
        self.assertEqual(full["static"]["states"]["gcc_analyzer"]["TOOL_ERROR"], 1)
        self.assertEqual(full["correctness"]["verdicts"]["build_failed"], 1)
        self.assertEqual(full["dynamic"]["states"]["asan_ubsan"]["TOOL_ERROR"], 1)
        self.assertEqual(full["enhanced"]["statuses"]["timeout"], 10)
        self.assertEqual(result["counts"]["pilot"]["correctness"]["verdicts"]["timeout"], 2)
        self.assertEqual(result["counts"]["pilot"]["static"]["states"]["infer"]["TIMEOUT"], 1)

    def test_missing_static_tool_fails(self):
        path = self.repo.ledger(TEST_RUN, "static.llov.jsonl")
        path.unlink()
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:plan_complete" % TEST_RUN,
                                           "full_ext:%s:static_coverage" % TEST_RUN])
        self.assertFalse(result["model_complete"])
        self.assertEqual(check(result, "full_ext:%s:static_coverage" % TEST_RUN)["detail"]["missing_entries"], 1)
        self.assertEqual(check(result, "full_ext:%s:plan_complete" % TEST_RUN)["detail"]["open_items"],
                         OrderedDict([("static.llov", 1)]))

    def test_pilot_missing_applicable_static_tool_fails(self):
        # the omp record never carried infer/parcoach (inapplicable) and passes
        self.assertNotIn("infer", read_jsonl(self.repo.run_path(pl.PILOT, pt.STATIC_FILE))[1]["tools"])

        def drop(rows):
            del rows[0]["tools"]["infer"]  # serial: infer applies
            return rows

        edit_jsonl(self.repo.run_path(pl.PILOT, pt.STATIC_FILE), drop)
        result = self.repo.verify()
        self.assertEqual(failing(result), ["pilot:%s:static_coverage" % pl.PILOT])
        self.assertEqual(check(result, "pilot:%s:static_coverage" % pl.PILOT)["detail"]["missing_entries"], 1)

    def test_missing_correctness_record_fails(self):
        write_jsonl(self.repo.ledger(STATIC_RUN, pt.CORRECTNESS_FILE), [])
        edit_jsonl(self.repo.run_path(PILOT_ITER, pt.CORRECTNESS_FILE), lambda rows: [])
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:correctness_coverage" % STATIC_RUN,
                                           "full_ext:%s:plan_complete" % STATIC_RUN,
                                           "pilot:%s:correctness_coverage" % PILOT_ITER])

    def test_dynamic_record_missing_applicable_tool_fails(self):
        def drop(rows):
            del rows[0]["tools"]["must"]  # omp: must does not apply
            return rows

        edit_jsonl(self.repo.run_path(TEST_RUN, pt.DYNAMIC_FILE), drop)
        self.assertEqual(failing(self.repo.verify()), [])

        def drop_applicable(rows):
            del rows[0]["tools"]["tsan"]  # omp: tsan applies
            return rows

        edit_jsonl(self.repo.run_path(TEST_RUN, pt.DYNAMIC_FILE), drop_applicable)
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:dynamic_coverage" % TEST_RUN])
        self.assertIn("/tsan", check(result, "full_ext:%s:dynamic_coverage" % TEST_RUN)["detail"]["examples"][0])

    def test_missing_enhanced_pair_fails(self):
        edit_jsonl(self.repo.ledger(pl.PARENT, pt.ENHANCED_FILE), lambda rows: rows[1:])
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:enhanced_pairs" % pl.PARENT,
                                           "full_ext:%s:plan_complete" % pl.PARENT])
        detail = check(result, "full_ext:%s:enhanced_pairs" % pl.PARENT)["detail"]
        self.assertEqual((detail["missing"], detail["unexpected"], detail["duplicates"]), (1, 0, 0))

    def test_extra_enhanced_pair_fails(self):
        def extra(rows):
            row = copy.deepcopy(rows[0])
            row["spec"]["size"] = 4093
            return rows + [row]

        edit_jsonl(self.repo.ledger(STATIC_RUN, pt.ENHANCED_FILE), extra)
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:enhanced_pairs" % STATIC_RUN,
                                           "full_ext:%s:plan_complete" % STATIC_RUN])
        detail = check(result, "full_ext:%s:enhanced_pairs" % STATIC_RUN)["detail"]
        self.assertEqual((detail["missing"], detail["unexpected"], detail["duplicates"]), (0, 1, 0))

    def test_duplicate_enhanced_pair_fails(self):
        edit_jsonl(self.repo.ledger(TEST_RUN, pt.ENHANCED_FILE), lambda rows: rows + [rows[3]])
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:enhanced_pairs" % TEST_RUN,
                                           "full_ext:%s:plan_complete" % TEST_RUN])
        detail = check(result, "full_ext:%s:enhanced_pairs" % TEST_RUN)["detail"]
        self.assertEqual((detail["missing"], detail["unexpected"], detail["duplicates"]), (0, 0, 1))

    def test_pilot_enhanced_pairs_are_exact(self):
        edit_jsonl(self.repo.run_path(PILOT_ITER, pt.ENHANCED_FILE), lambda rows: rows + [rows[0]])
        result = self.repo.verify()
        self.assertEqual(failing(result), ["pilot:%s:enhanced_pairs" % PILOT_ITER])
        self.assertEqual(check(result, "pilot:%s:enhanced_pairs" % PILOT_ITER)["detail"]["duplicates"], 1)

    def test_drifted_candidate_source_fails_registration(self):
        sample = self.repo.table.get("%s/%s" % (MODEL, STATIC_RUN)).document["samples"][0]
        (self.root / sample["source_path"]).write_bytes(b"// changed after registration\n")
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:enhanced_registration" % STATIC_RUN])
        detail = check(result, "full_ext:%s:enhanced_registration" % STATIC_RUN)["detail"]
        self.assertNotEqual(detail["registered"], detail["recomputed"])
        self.assertEqual(detail["drifted_samples"], [sample["sample_id"]])

    def test_candidate_fingerprint_is_injectable(self):
        calls = []

        def stub(root, target):
            calls.append(target.target_id)
            return OrderedDict([("model_id", target.model_id), ("run_id", target.source_run),
                                ("sample_count", 0), ("combined_sha256", "0" * 64), ("samples", [])])

        result = self.repo.verify(candidate_fingerprint=stub)
        self.assertEqual(sorted(calls), sorted(t.target_id for t in self.repo.table.targets))
        self.assertEqual(failing(result), ["full_ext:%s:enhanced_registration" % run
                                           for run in sorted((pl.PARENT, STATIC_RUN, TEST_RUN))])

    def test_missing_registration_fails(self):
        self.repo.ledger(TEST_RUN, pt.ENHANCED_REGISTRATION_FILE).unlink()
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:enhanced_registration" % TEST_RUN])

    def test_registration_of_another_target_fails(self):
        shutil.copyfile(str(self.repo.ledger(STATIC_RUN, pt.ENHANCED_REGISTRATION_FILE)),
                        str(self.repo.ledger(TEST_RUN, pt.ENHANCED_REGISTRATION_FILE)))
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:enhanced_registration" % TEST_RUN])
        self.assertIn("another target", check(result, "full_ext:%s:enhanced_registration" % TEST_RUN)["detail"])

    def test_foreign_binding_fails(self):
        def foreign(rows):
            rows[0]["phase2_binding"]["contract_sha256"] = "f" * 64
            return rows

        edit_jsonl(self.repo.ledger(STATIC_RUN, pt.CORRECTNESS_FILE), foreign)
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:phase2_binding" % STATIC_RUN])
        detail = check(result, "full_ext:%s:phase2_binding" % STATIC_RUN)["detail"]
        self.assertEqual(detail["foreign"], OrderedDict([(pt.CORRECTNESS_FILE, 1)]))
        self.assertIn("foreign contract_sha256", detail["examples"][0])

    def test_static_row_with_unregistered_invocation_fails(self):
        def foreign(rows):
            rows[0]["invocation_sha256"] = sha("another invocation")
            return rows

        edit_jsonl(self.repo.ledger(TEST_RUN, "static.parcoach.jsonl"), foreign)
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:phase2_binding" % TEST_RUN])
        self.assertIn("unregistered invocation_sha256 for static.parcoach",
                      check(result, "full_ext:%s:phase2_binding" % TEST_RUN)["detail"]["examples"][0])

    def test_phase2_rows_without_recorded_binding_fail(self):
        result = self.repo.verify(binding=None)
        self.assertEqual(failing(result), ["full_ext:%s:phase2_binding" % run
                                           for run in sorted((pl.PARENT, STATIC_RUN, TEST_RUN))])

    def test_foreign_provenance_fails(self):
        def foreign(rows):
            rows[0]["candidate_source_sha256"] = "0" * 64
            return rows

        edit_jsonl(self.repo.ledger(pl.PARENT, pt.ENHANCED_GROUPS_FILE), foreign)
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:%s:phase2_provenance" % pl.PARENT])

    def test_stray_phase2_ledger_fails(self):
        stray = self.root / pt.ledger_relative(MODEL, pl.EXCLUDED_HISTORICAL_RUNS[0], "static.llov.jsonl")
        write_jsonl(stray, [])
        torn = self.repo.ledger(TEST_RUN, pt.ENHANCED_FILE.replace(".jsonl", ".jsonl.torn"))
        torn.write_text("{}\n", encoding="utf-8")
        result = self.repo.verify()
        self.assertEqual(failing(result), ["full_ext:phase2_ledgers_bound_to_targets"])
        detail = check(result, "full_ext:phase2_ledgers_bound_to_targets")["detail"]
        self.assertEqual(detail["stray"], [pl.EXCLUDED_HISTORICAL_RUNS[0]])
        self.assertEqual(detail["archived_torn_tails"], ["%s/enhanced_tests.jsonl.torn" % TEST_RUN])

    def test_torn_phase2_ledger_fails(self):
        with self.repo.ledger(STATIC_RUN, pt.DYNAMIC_FILE).open("a", encoding="utf-8") as handle:
            handle.write('{"sample_id": "torn')
        result = self.repo.verify()
        self.assertIn("full_ext:%s:dynamic_coverage" % STATIC_RUN, failing(result))
        self.assertIn("TornLedger", check(result, "full_ext:%s:dynamic_coverage" % STATIC_RUN)["detail"])

    def test_global_checks_block_completion(self):
        result = self.repo.verify(immutability=OrderedDict([("status", pv.FAIL), ("detail", "changed")]))
        self.assertEqual(failing(result), ["global:immutability"])
        self.assertFalse(result["model_complete"])
        self.repo.lineage.targets_sha256 = "0" * 64
        self.assertEqual(failing(self.repo.verify()), ["global:target_table_bound_to_lineage"])
        result = pv.verify_model(self.root, CONFIG, self.repo.table, MODEL, None, self.repo.deep())
        self.assertIn("global:target_table_bound_to_lineage", failing(result))

    def test_population_and_immutability_are_computed_when_not_injected(self):
        deep = self.repo.deep()
        del deep["immutability"]
        del deep["population"]
        result = pv.verify_model(self.root, CONFIG, self.repo.table, MODEL, self.repo.lineage, deep)
        # immutability from lineage.verify() (fake: passes); the temp repo has no composite study
        self.assertEqual(failing(result), ["global:population"])
        self.assertEqual(check(result, "global:immutability")["detail"]["lineage_sha256"], "e" * 64)

    def test_recorded_binding_reads_the_run_fragments(self):
        from thesis.evaluation import manifest_fragments as mf

        self.assertIsNone(pv.recorded_binding(self.root))
        intermediate = self.root / pt.INTERMEDIATE_REL
        mf.register_fragment(intermediate, pl.SUCCESSOR, "contract", None,
                             OrderedDict([("contract_sha256", CONTRACT), ("contract", {})]), fingerprint=CONTRACT)
        mf.register_fragment(intermediate, pl.SUCCESSOR, "authorization", "start",
                             OrderedDict([("authorization_sha256", AUTHORIZATION)]))
        for stage in pl.STAGES:
            runtime = sha("runtime:" + stage)
            mf.register_fragment(intermediate, pl.SUCCESSOR, "runtime", "stage." + stage,
                                 OrderedDict([("stage", stage), ("stage_runtime_sha256", runtime)]),
                                 fingerprint=runtime)
            mf.register_fragment(intermediate, pl.SUCCESSOR, "invocation", "%s@%s@x" % (stage, MODEL),
                                 OrderedDict([("stage", stage), ("invocation_sha256",
                                                                 sha("invocation:%s:%s" % (stage, MODEL)))]))
        refused = mf.fragments_dir(intermediate, pl.SUCCESSOR) / mf.HISTORY_DIR_NAME / "runtime.stage.dynamic.x.1.json"
        refused.write_text(json.dumps({"outcome": "REFUSED", "content": {
            "stage": "dynamic", "stage_runtime_sha256": "9" * 64}}), encoding="utf-8")
        binding = pv.recorded_binding(self.root)
        self.assertEqual(json.loads(json.dumps(binding)), json.loads(json.dumps(EXPECTED_BINDING)))
        result = self.repo.verify(binding=binding)
        self.assertEqual(failing(result), [])

    def test_verify_all_writes_reports_only_when_asked(self):
        summary = pv.verify_all(self.root, CONFIG, self.repo.table, self.repo.lineage, models=[MODEL],
                                write=False, deep_checks=self.repo.deep())
        self.assertTrue(summary["models"][MODEL]["model_complete"])
        self.assertFalse((self.root / pv.VERIFICATION_REL).exists())
        summary = pv.verify_all(self.root, CONFIG, self.repo.table, self.repo.lineage, models=[MODEL],
                                write=True, deep_checks=self.repo.deep())
        path = self.root / summary["reports"][MODEL]
        self.assertEqual(summary["reports"][MODEL],
                         "%s/verification/%s.phase2_verification.json" % (pl.RESULTS_REL, MODEL))
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((document["status"], document["model_complete"]), (pv.PASS, True))
        self.assertIn("written_at_utc", document)
        self.assertTrue(summary["models_complete"])
        with self.assertRaises(RecoveryRefused):
            pv.verify_all(self.root, CONFIG, self.repo.table, self.repo.lineage, models=["not_a_model"],
                          deep_checks=self.repo.deep())


class CompositeTest(SyntheticRepoTest):
    def cells(self):
        return list(pc.iter_cells(self.root, CONFIG, self.repo.table, models=[MODEL]))

    def test_cells_cover_every_sample_once_with_owner(self):
        cells = self.cells()
        keys = [(c["block"], c["source_run"], c["sample_id"]) for c in cells]
        self.assertEqual(len(keys), len(set(keys)))
        expected = set((pc.PILOT_BLOCK, run, s["sample_id"]) for run, samples in self.repo.pilot.items()
                       for s in samples)
        expected |= set((pc.FULL_BLOCK, t.source_run, sid) for t in self.repo.table.targets for sid in t.samples)
        self.assertEqual(set(keys), expected)
        by_run = OrderedDict()
        for cell in cells:
            by_run.setdefault(cell["source_run"], []).append(cell)
        for run in (pl.PILOT, PILOT_ITER):
            for cell in by_run[run]:
                self.assertEqual(cell["owner"], pl.PILOT)
                self.assertEqual([cell[s]["owner"] for s in pc.STAGES], [pl.PILOT] * 4)
                self.assertEqual(cell["enhanced"]["pairs"], 20)
        self.assertEqual([c["iteration"] for c in by_run[PILOT_ITER]], [1])
        for cell in by_run[pl.PARENT]:
            self.assertEqual((cell["owner"], cell["variant"], cell["iteration"]), (pl.PARENT, None, 0))
            self.assertEqual([cell[s]["owner"] for s in pc.STAGES], [pl.PARENT] * 3 + [pl.SUCCESSOR])
        static_cell = by_run[STATIC_RUN][0]
        self.assertEqual(static_cell["owner"], STATIC_RUN)
        self.assertEqual([static_cell[s]["owner"] for s in pc.STAGES],
                         [STATIC_RUN, pl.SUCCESSOR, pl.SUCCESSOR, pl.SUCCESSOR])
        self.assertEqual(static_cell["correctness"]["verdict"], "pass")
        test_cell = by_run[TEST_RUN][0]
        self.assertEqual(test_cell["static"]["owner"], TEST_RUN)
        self.assertEqual(test_cell["static"]["supplemented"],
                         OrderedDict([("parcoach", pl.SUCCESSOR), ("llov", pl.SUCCESSOR)]))
        self.assertEqual(test_cell["static"]["tools"]["parcoach"], "NOT_APPLICABLE")
        self.assertEqual(test_cell["dynamic"]["tools"]["tsan"],
                         OrderedDict([("analysis_state", "COMPLETED"), ("ran", True)]))
        self.assertEqual(test_cell["source_sha256"], self.repo.table.get("%s/%s" % (MODEL, TEST_RUN))
                         .samples[test_cell["sample_id"]]["source_sha256"])

    def test_missing_evidence_is_none_and_duplicates_refuse(self):
        write_jsonl(self.repo.ledger(STATIC_RUN, pt.CORRECTNESS_FILE), [])
        cell = [c for c in self.cells() if c["source_run"] == STATIC_RUN][0]
        self.assertIsNone(cell["correctness"])
        edit_jsonl(self.repo.ledger(STATIC_RUN, pt.DYNAMIC_FILE), lambda rows: rows + rows)
        with self.assertRaises(RecoveryRefused):
            self.cells()

    def write_contracts(self):
        from thesis.evaluation import pilot_run_contract as prc

        for run in pc.DERIVED_RUNS:
            contract = OrderedDict([("schema_version", "run_contract.v1"), ("run_id", run), ("status", "READY")])
            contract["contract_sha256"] = prc.contract_sha256(contract)
            path = self.root / "thesis/evaluation/recovery" / run / "contract.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(contract), encoding="utf-8")

    def document(self, population=None):
        population = population or OrderedDict([
            ("source", pc.COMPOSITE_STUDY_REL), ("base_cells", 1980),
            ("per_run", OrderedDict([(pl.PARENT, 1584), (pl.PILOT, 396)]))])
        totals = OrderedDict([("enhanced", OrderedDict([("items", 0), ("targets_open", 0)]))])
        return pc.composite_document(self.root, CONFIG, self.repo.table, "e" * 64, totals,
                                     population=population, models=[MODEL])

    def test_composite_document_is_deterministic(self):
        self.write_contracts()
        first = self.document()
        second = self.document()
        self.assertEqual(json.dumps(first), json.dumps(second))
        self.assertTrue(pc.verify_document(first))
        body = OrderedDict((k, v) for k, v in first.items() if k != "composite_sha256")
        self.assertEqual(first["composite_sha256"], canonical_sha256(body))
        self.assertEqual(first["schema_version"], "phase2_composite.v1")
        self.assertEqual(first["population"]["base_cells"], 1980)
        self.assertEqual(first["population"]["derived_base_cells"], 0)
        self.assertEqual([d["run_id"] for d in first["derived_lineages"]], list(pc.DERIVED_RUNS))
        self.assertEqual(set(d["base_cells"] for d in first["derived_lineages"]), set([0]))
        self.assertTrue(all(len(d["contract_sha256"]) == 64 for d in first["derived_lineages"]))
        self.assertEqual(first["cells"]["per_block"], OrderedDict([("pilot", 3), ("full_ext", 4)]))
        self.assertEqual(first["cells"]["base_per_block"], OrderedDict([("pilot", 2), ("full_ext", 2)]))
        self.assertEqual(first["cells"]["candidates"], OrderedDict([
            ("pilot", OrderedDict([("test_feedback", OrderedDict([("iter1", 1)]))])),
            ("full_ext", OrderedDict([("static_feedback", OrderedDict([("iter1", 1)])),
                                      ("test_feedback", OrderedDict([("iter1", 1)]))]))]))
        coverage = first["stage_coverage"]
        self.assertEqual(coverage["full_ext"]["correctness"]["owners"],
                         OrderedDict([(pl.PARENT, 2), (pl.SUCCESSOR, 1), (TEST_RUN, 1)]))
        self.assertEqual(coverage["full_ext"]["enhanced"]["pairs"], 80)
        self.assertEqual(coverage["full_ext"]["static"]["supplemented_by"], OrderedDict([(pl.SUCCESSOR, 2)]))
        self.assertEqual(coverage["pilot"]["enhanced"]["pairs"], 60)
        self.assertEqual(first["plan_totals"]["enhanced"]["items"], 0)
        tampered = copy.deepcopy(first)
        tampered["cells"]["total"] = 8
        with self.assertRaises(RecoveryRefused):
            pc.verify_document(tampered)
        path = pc.write_document(self.root, first)
        self.assertEqual(path.relative_to(self.root.resolve()).as_posix(), pc.DOCUMENT_REL)
        with self.assertRaises(RecoveryRefused):
            pc.write_document(self.root, first, relative="thesis/results/intermediate/pilot_002/x.json")

    def test_composite_document_refuses_wrong_population_and_missing_contract(self):
        self.write_contracts()
        with self.assertRaises(RecoveryRefused):
            self.document(OrderedDict([("base_cells", 1979),
                                       ("per_run", OrderedDict([(pl.PARENT, 1583), (pl.PILOT, 396)]))]))
        (self.root / "thesis/evaluation/recovery/full_ext_recovery_002/contract.json").unlink()
        with self.assertRaises(RecoveryRefused):
            self.document()
        self.write_contracts()
        (self.root / "thesis/evaluation/recovery" / pl.SUCCESSOR / "contract.json").unlink()
        self.assertIsNone(self.document()["derived_lineages"][-1]["contract_sha256"])


if __name__ == "__main__":
    unittest.main()
