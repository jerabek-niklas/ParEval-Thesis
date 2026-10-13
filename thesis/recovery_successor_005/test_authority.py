"""Synthetic tests of the phase-2 core: target table (owners, exclusion,
request binding, source binding, held-out gate), presence semantics
(history + 002/003 supplements + phase-2 ledgers), plan assignment,
protected inventories, write confinement, stage scheduling, effective
invocations, provider isolation and the equivalence obligations.

Python 3.8 compatible (runs in all three pinned interpreters).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / pl.CONFIG_REL
MODELS = ("m_alpha", "m_beta")
PILOT_BENCH = ("search", "30_search_first")
FULL_BENCH = ("dense_la", "01_dense_la_solve")
EXEC_MODELS = ("serial", "omp", "mpi")


def load_config():
    from thesis.config.load_config import load_config as _load

    return _load(str(CONFIG_PATH))


def sample_id(model, bench, execution_model, index=0):
    return "%s__%s__%s__%s__sample_%d" % (model, bench[0], bench[1], execution_model, index)


class World:
    """A miniature repository: pilot_002 (complete loops), full_ext_001 base,
    m_alpha continued by 003 (static/combined) with a recovery_001-native test
    loop, m_beta fresh in 004, plus the aborted parent repair that must never
    become a target."""

    def __init__(self, root):
        self.root = Path(root)
        self.intermediate = self.root / "thesis/results/intermediate"

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def jsonl(self, relative, rows):
        return self.write(relative, "".join(json.dumps(r) + "\n" for r in rows))

    def assembly(self, run, model, ids, bench, tamper=None):
        rows = []
        for sid in ids:
            source_rel = "thesis/results/intermediate/%s/%s/sources/%s/generated-code.hpp" % (run, model, sid)
            text = "// %s %s\nint f() { return 1; }\n" % (run, sid)
            self.write(source_rel, text)
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if tamper == sid:
                sha = "0" * 64
            rows.append(OrderedDict([
                ("schema_version", "assembly.v2"), ("run_id", run), ("model_id", model), ("sample_id", sid),
                ("execution_model", sid.split("__")[-2]), ("benchmark", "%s/%s" % bench),
                ("assembled", True), ("source_path", source_rel), ("source_sha256", sha),
                ("drivers", {"benchmark_dir": "drivers/cpp/benchmarks/%s/%s" % bench,
                             "model_driver": "drivers/cpp/models/x.cc"})]))
        self.jsonl("thesis/results/intermediate/%s/%s/assembly.jsonl" % (run, model), rows)
        return rows

    def static_records(self, run, model, ids, tools):
        rows = []
        for sid in ids:
            rows.append(OrderedDict([("run_id", run), ("model_id", model), ("sample_id", sid),
                                     ("tools", OrderedDict((t, {"tool": t, "analysis_state": "COMPLETED"})
                                                           for t in tools))]))
        self.jsonl("thesis/results/intermediate/%s/%s/static_analysis.jsonl" % (run, model), rows)

    def stage_records(self, run, model, ids, name):
        self.jsonl("thesis/results/intermediate/%s/%s/%s" % (run, model, name),
                   [OrderedDict([("run_id", run), ("model_id", model), ("sample_id", sid),
                                 ("verdict", "pass")]) for sid in ids])

    def loop(self, owner, model, variant, iteration, rows, predecessor=None):
        base = "thesis/results/intermediate/%s/%s/repair/%s" % (owner, model, variant)
        wave = OrderedDict([("run_id", owner), ("model_id", model), ("variant", variant),
                            ("iteration", iteration), ("phase", "done"), ("repair_condition_sha256", "c" * 64)])
        if predecessor:
            wave["predecessor_run_id"] = predecessor
        self.write(base + "/wave_state.json", json.dumps(wave))
        self.jsonl(base + "/state.jsonl", [OrderedDict([("run_id", owner), ("model_id", model), ("variant", variant),
                                                        ("sample_id", sid), ("iteration", it), ("status", status)])
                                           for sid, it, status in rows])

    def requests(self, owner, model, variant, iteration, ids):
        self.jsonl("thesis/results/intermediate/%s/%s/repair/%s/iter%d/requests.jsonl"
                   % (owner, model, variant, iteration), [{"sample_id": s} for s in ids])

    def build(self):
        all_static = ("compiler", "gcc_analyzer", "clang_tidy", "cppcheck", "infer", "parcoach", "llov")
        for model in MODELS:
            pilot_ids = [sample_id(model, PILOT_BENCH, em) for em in EXEC_MODELS]
            self.assembly("pilot_002", model, pilot_ids, PILOT_BENCH)
            for variant in pl.VARIANTS:
                self.loop("pilot_002", model, variant, 1, [(s, 0, "stopped_clean") for s in pilot_ids])
            base_ids = [sample_id(model, FULL_BENCH, em) for em in EXEC_MODELS]
            self.assembly("full_ext_001", model, base_ids, FULL_BENCH)
            self.static_records("full_ext_001", model, base_ids, all_static)
            self.stage_records("full_ext_001", model, base_ids, "correctness.jsonl")
            self.stage_records("full_ext_001", model, base_ids, "dynamic_analysis.jsonl")
        alpha = [sample_id("m_alpha", FULL_BENCH, em) for em in EXEC_MODELS]
        # recovery_001 native test loop: iteration 1 for two samples
        self.loop("full_ext_recovery_001", "m_alpha", "test_feedback", 1,
                  [(s, 0, "active") for s in alpha] + [(alpha[0], 1, "stopped_budget"),
                                                       (alpha[1], 1, "stopped_tests_pass"),
                                                       (alpha[2], 0, "stopped_tests_pass")])
        self.requests("full_ext_recovery_001", "m_alpha", "test_feedback", 1, alpha[:2])
        run = "full_ext_recovery_001__test_feedback__iter1"
        self.assembly(run, "m_alpha", alpha[:2], FULL_BENCH)
        self.static_records(run, "m_alpha", alpha[:2], ("compiler",))
        self.stage_records(run, "m_alpha", alpha[:2], "correctness.jsonl")
        self.stage_records(run, "m_alpha", alpha[:2], "dynamic_analysis.jsonl")
        # static/combined: recovery_001 iteration 1, continued by 003 (iteration 2)
        for variant in ("static_feedback", "combined_feedback"):
            self.loop("full_ext_recovery_001", "m_alpha", variant, 1, [(s, 0, "active") for s in alpha])
            self.requests("full_ext_recovery_001", "m_alpha", variant, 1, alpha)
            run1 = "full_ext_recovery_001__%s__iter1" % variant
            self.assembly(run1, "m_alpha", alpha, FULL_BENCH)
            self.static_records(run1, "m_alpha", alpha, all_static[:5])
            self.loop("full_ext_recovery_003", "m_alpha", variant, 2,
                      [(alpha[0], 1, "active"), (alpha[1], 1, "stopped_clean"), (alpha[2], 1, "stopped_clean"),
                       (alpha[0], 2, "stopped_budget")], predecessor="full_ext_recovery_001")
            self.requests("full_ext_recovery_003", "m_alpha", variant, 2, alpha[:1])
            run2 = "full_ext_recovery_003__%s__iter2" % variant
            self.assembly(run2, "m_alpha", alpha[:1], FULL_BENCH)
            self.static_records(run2, "m_alpha", alpha[:1], all_static)
            if variant == "combined_feedback":
                for r, ids in ((run1, alpha), (run2, alpha[:1])):
                    self.stage_records(r, "m_alpha", ids, "correctness.jsonl")
                    self.stage_records(r, "m_alpha", ids, "dynamic_analysis.jsonl")
            for tool in ("parcoach", "llov"):
                rows = [OrderedDict([("schema_version", "successor_static_supplement.v1"),
                                     ("run_id", "full_ext_recovery_003"), ("candidate_source_run", run1),
                                     ("model_id", "m_alpha"), ("tool", tool), ("sample_id", s),
                                     ("execution_model", s.split("__")[-2]),
                                     ("candidate_source_sha256", self.source_sha(run1, "m_alpha", s)),
                                     ("entry", {"tool": tool, "analysis_state": "COMPLETED"})]) for s in alpha]
                self.jsonl("thesis/results/intermediate/full_ext_recovery_003/m_alpha/supplements/%s/static.%s.jsonl"
                           % (run1, tool), rows)
        # m_beta: fresh 004 loops, iteration 1 only
        beta = [sample_id("m_beta", FULL_BENCH, em) for em in EXEC_MODELS]
        for variant in pl.VARIANTS:
            self.loop("full_ext_recovery_004", "m_beta", variant, 1,
                      [(s, 0, "active") for s in beta] + [(s, 1, "stopped_budget") for s in beta[:2]]
                      + [(beta[2], 0, "stopped_clean")])
            self.requests("full_ext_recovery_004", "m_beta", variant, 1, beta[:2])
            run = "full_ext_recovery_004__%s__iter1" % variant
            self.assembly(run, "m_beta", beta[:2], FULL_BENCH)
            tools = ("compiler",) if variant == "test_feedback" else all_static
            self.static_records(run, "m_beta", beta[:2], tools)
            if variant != "static_feedback":
                self.stage_records(run, "m_beta", beta[:2], "correctness.jsonl")
                self.stage_records(run, "m_beta", beta[:2], "dynamic_analysis.jsonl")
        # the aborted parent repair: never a target
        self.assembly("full_ext_001__static_feedback__iter1", "m_alpha", alpha, FULL_BENCH)
        return self

    def source_sha(self, run, model, sid):
        path = self.root / ("thesis/results/intermediate/%s/%s/sources/%s/generated-code.hpp" % (run, model, sid))
        return hashlib.sha256(path.read_bytes()).hexdigest()


class TargetTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.world = World(self.tmp).build()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def table(self):
        document = pt.build_table(self.tmp, models=MODELS)
        return pt.TargetTable(self.tmp, document, document["table_sha256"], models=MODELS)

    def test_targets_owners_and_exclusion(self):
        table = self.table()
        ids = [t.target_id for t in table.targets]
        self.assertEqual(ids, [
            "m_alpha/full_ext_001",
            "m_alpha/full_ext_recovery_001__static_feedback__iter1",
            "m_alpha/full_ext_recovery_003__static_feedback__iter2",
            "m_alpha/full_ext_recovery_001__test_feedback__iter1",
            "m_alpha/full_ext_recovery_001__combined_feedback__iter1",
            "m_alpha/full_ext_recovery_003__combined_feedback__iter2",
            "m_beta/full_ext_001",
            "m_beta/full_ext_recovery_004__static_feedback__iter1",
            "m_beta/full_ext_recovery_004__test_feedback__iter1",
            "m_beta/full_ext_recovery_004__combined_feedback__iter1"])
        self.assertNotIn("full_ext_001__static_feedback__iter1", [t.source_run for t in table.targets])
        self.assertEqual(dict(table.document["sample_totals"]),
                         {"base": 6, "static_feedback": 6, "test_feedback": 4, "combined_feedback": 6})
        continued = table.get("m_alpha/full_ext_recovery_001__static_feedback__iter1")
        self.assertEqual((continued.loop_owner, continued.iteration), ("full_ext_recovery_003", 1))
        self.assertEqual(pt.build_table(self.tmp, models=MODELS)["table_sha256"], table.sha256)

    def test_candidates_must_equal_the_loop_requests(self):
        self.world.requests("full_ext_recovery_004", "m_beta", "static_feedback", 1,
                            [sample_id("m_beta", FULL_BENCH, "serial")])
        with self.assertRaises(RecoveryRefused):
            pt.build_table(self.tmp, models=MODELS)

    def test_source_hash_binding(self):
        ids = [sample_id("m_beta", FULL_BENCH, em) for em in ("serial", "omp")]
        self.world.assembly("full_ext_recovery_004__static_feedback__iter1", "m_beta", ids, FULL_BENCH,
                            tamper=ids[0])
        with self.assertRaises(RecoveryRefused):
            pt.build_table(self.tmp, models=MODELS)

    def test_held_out_gate_requires_every_loop_terminal(self):
        self.world.loop("full_ext_recovery_004", "m_beta", "combined_feedback", 1,
                        [(s, 0, "active") for s in [sample_id("m_beta", FULL_BENCH, em) for em in EXEC_MODELS]])
        with self.assertRaises(RecoveryRefused):
            pt.build_table(self.tmp, models=MODELS)

    def test_assembled_samples_detect_drift(self):
        table = self.table()
        target = table.get("m_beta/full_ext_recovery_004__static_feedback__iter1")
        self.assertEqual([s.sample_id for s in pt.assembled_samples(self.tmp, target)], list(target.samples))
        source = Path(self.tmp) / target.samples[list(target.samples)[0]]["source_path"]
        source.write_bytes(source.read_bytes() + b"// drift\n")
        with self.assertRaises(RecoveryRefused):
            pt.assembled_samples(self.tmp, target)

    def test_table_refuses_tampering_and_excluded_runs(self):
        document = pt.build_table(self.tmp, models=MODELS)
        bad = json.loads(json.dumps(document), object_pairs_hook=OrderedDict)
        bad["targets"][0]["sample_count"] = 99
        with self.assertRaises(RecoveryRefused):
            pt.TargetTable(self.tmp, bad, models=MODELS)
        bad = json.loads(json.dumps(document), object_pairs_hook=OrderedDict)
        bad["targets"][1]["source_run"] = "full_ext_001__static_feedback__iter1"
        body = OrderedDict((k, v) for k, v in bad.items() if k != "table_sha256")
        bad["table_sha256"] = canonical_sha256(body)
        with self.assertRaises(RecoveryRefused):
            pt.TargetTable(self.tmp, bad, models=MODELS)


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.world = World(self.tmp).build()
        document = pt.build_table(self.tmp, models=MODELS)
        self.table = pt.TargetTable(self.tmp, document, models=MODELS)
        self.config = load_config()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def supplement_row(self, target, sid, tool, entry=None, **overrides):
        row = OrderedDict([("schema_version", "successor_static_supplement.v1"), ("run_id", pl.SUCCESSOR),
                           ("authority_run_id", pl.SUCCESSOR), ("candidate_source_run", target.source_run),
                           ("model_id", target.model_id), ("variant", target.variant),
                           ("iteration", target.iteration), ("sample_id", sid),
                           ("execution_model", target.samples[sid]["execution_model"]), ("tool", tool),
                           ("candidate_source_sha256", target.samples[sid]["source_sha256"]),
                           ("entry", entry or {"tool": tool, "analysis_state": "TIMEOUT"})])
        row.update(overrides)
        return row

    def test_historical_supplements_complete_the_static_view(self):
        target = self.table.get("m_alpha/full_ext_recovery_001__static_feedback__iter1")
        self.assertEqual(pg.missing_static(self.tmp, self.config, target), OrderedDict())

    def test_missing_static_and_phase2_rows(self):
        target = self.table.get("m_beta/full_ext_recovery_004__test_feedback__iter1")
        missing = pg.missing_static(self.tmp, self.config, target)
        self.assertEqual(sorted(missing), sorted(target.samples))
        self.assertNotIn("compiler", missing[list(missing)[0]])
        sid = list(target.samples)[0]
        self.world.jsonl(pt.ledger_relative(target.model_id, target.source_run, "static.infer.jsonl"),
                         [self.supplement_row(target, sid, "infer")])
        after = pg.missing_static(self.tmp, self.config, target)
        self.assertNotIn("infer", after[sid])  # a TIMEOUT entry is present, never re-measured
        self.world.jsonl(pt.ledger_relative(target.model_id, target.source_run, "static.compiler.jsonl"),
                         [self.supplement_row(target, sid, "compiler")])
        with self.assertRaises(RecoveryRefused):  # a phase-2 entry may never shadow a historical one
            pg.missing_static(self.tmp, self.config, target)

    def test_foreign_or_duplicate_phase2_rows_refuse(self):
        target = self.table.get("m_beta/full_ext_recovery_004__test_feedback__iter1")
        sid = list(target.samples)[0]
        relative = pt.ledger_relative(target.model_id, target.source_run, "static.cppcheck.jsonl")
        self.world.jsonl(relative, [self.supplement_row(target, sid, "cppcheck")] * 2)
        with self.assertRaises(RecoveryRefused):
            pg.missing_static(self.tmp, self.config, target)
        self.world.jsonl(relative, [self.supplement_row(target, sid, "cppcheck", candidate_source_sha256="1" * 64)])
        with self.assertRaises(RecoveryRefused):
            pg.missing_static(self.tmp, self.config, target)

    def test_records_history_or_phase2_never_both(self):
        target = self.table.get("m_beta/full_ext_recovery_004__static_feedback__iter1")
        self.assertEqual(pg.missing_records(self.tmp, target, pt.CORRECTNESS_FILE), list(target.samples))
        sid = list(target.samples)[0]
        row = OrderedDict([("run_id", target.source_run), ("model_id", target.model_id), ("sample_id", sid),
                           ("verdict", "build_failed")])
        row.update(pt.provenance(target, sid))
        relative = pt.ledger_relative(target.model_id, target.source_run, pt.CORRECTNESS_FILE)
        self.world.jsonl(relative, [row])
        self.assertEqual(pg.missing_records(self.tmp, target, pt.CORRECTNESS_FILE), list(target.samples)[1:])
        foreign = OrderedDict(row, candidate_source_sha256="2" * 64)
        self.world.jsonl(relative, [foreign])
        with self.assertRaises(RecoveryRefused):
            pg.missing_records(self.tmp, target, pt.CORRECTNESS_FILE)
        combined = self.table.get("m_beta/full_ext_recovery_004__combined_feedback__iter1")
        sid = list(combined.samples)[0]
        dup = OrderedDict([("run_id", combined.source_run), ("model_id", combined.model_id), ("sample_id", sid)])
        dup.update(pt.provenance(combined, sid))
        self.world.jsonl(pt.ledger_relative(combined.model_id, combined.source_run, pt.CORRECTNESS_FILE), [dup])
        with self.assertRaises(RecoveryRefused):
            pg.missing_records(self.tmp, combined, pt.CORRECTNESS_FILE)

    def test_torn_ledger_is_reported_not_repaired(self):
        target = self.table.get("m_beta/full_ext_recovery_004__static_feedback__iter1")
        path = self.world.write(pt.ledger_relative(target.model_id, target.source_run, pt.DYNAMIC_FILE),
                                '{"sample_id": "x"')
        with self.assertRaises(pg.TornLedger):
            pg.missing_records(self.tmp, target, pt.DYNAMIC_FILE)
        self.assertEqual(path.read_bytes(), b'{"sample_id": "x"')

    def test_undecodable_ledger_line_is_an_integrity_refusal(self):
        target = self.table.get("m_beta/full_ext_recovery_004__static_feedback__iter1")
        self.world.write(pt.ledger_relative(target.model_id, target.source_run, pt.CORRECTNESS_FILE),
                         "{not json}\n")
        with self.assertRaises(RecoveryRefused) as raised:
            pg.missing_records(self.tmp, target, pt.CORRECTNESS_FILE)
        self.assertIn("undecodable", str(raised.exception))

    def test_plan_assignment_and_integrity_findings(self):
        from thesis.recovery_successor_005 import plan as pp

        result = pp.plan(self.tmp, self.config, self.table, with_enhanced=False)
        totals = result["totals"]
        self.assertEqual(totals["correctness"]["items"], 6)
        self.assertEqual(totals["static.main"]["samples"], 4)
        self.assertEqual(totals["static.main"]["applicable.infer"], 2)  # the two serial test samples
        self.assertEqual(result["integrity_findings"], [])
        combined = self.table.get("m_beta/full_ext_recovery_004__combined_feedback__iter1")
        (Path(self.tmp) / pt.run_dir(combined.source_run, combined.model_id) / pt.CORRECTNESS_FILE).unlink()
        result = pp.plan(self.tmp, self.config, self.table, with_enhanced=False)
        self.assertEqual(len(result["integrity_findings"]), 1)
        self.assertNotIn("correctness", result["targets"][combined.target_id])


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.world = World(self.tmp).build()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_inventory_detects_byte_and_membership_changes(self):
        inventory = pl.protected_inventory(self.tmp, "full_ext_recovery_003")
        self.assertTrue(pl.verify_protected(self.tmp, inventory))
        state = self.world.root / "thesis/results/intermediate/full_ext_recovery_003/m_alpha/repair/static_feedback/state.jsonl"
        original = state.read_bytes()
        state.write_bytes(original + b"\n")
        with self.assertRaises(RecoveryRefused):
            pl.verify_protected(self.tmp, inventory)
        state.write_bytes(original)
        extra = self.world.write("thesis/results/intermediate/full_ext_recovery_003__static_feedback__iter2/m_alpha/new.json", "{}")
        with self.assertRaises(RecoveryRefused):
            pl.verify_protected(self.tmp, inventory)
        extra.unlink()
        self.assertTrue(pl.verify_protected(self.tmp, inventory))
        with self.assertRaises(RecoveryRefused):
            pl.run_tree_paths(self.tmp, "full_ext_phase2_001")

    def test_writes_are_confined_to_the_phase2_tree(self):
        self.assertTrue(pl.require_writable(self.tmp, pt.ledger_relative("m_alpha", "full_ext_001", "x.jsonl")))
        for relative in ("thesis/results/intermediate/full_ext_recovery_004/m_beta/x.jsonl",
                         "thesis/results/intermediate/full_ext_001/m_alpha/x.jsonl",
                         "thesis/results/intermediate/pilot_002__static_feedback__iter1/m/x.jsonl",
                         "thesis/evaluation/recovery/full_ext_phase2_001/contract.json",
                         "thesis/results/intermediate/full_ext_phase2_001/../full_ext_001/x"):
            with self.assertRaises(RecoveryRefused, msg=relative):
                pl.require_writable(self.tmp, relative)
        self.assertTrue(pl.is_protected_relative("thesis/results/raw/full_ext_recovery_002__x__iter2/m/a"))
        self.assertFalse(pl.is_protected_relative("thesis/results/intermediate/full_ext_phase2_001/m/a"))
        for bad in ("../x", "a/b", ".hidden", ""):
            with self.assertRaises(RecoveryRefused):
                pt.ledger_relative("m_alpha", bad, "x.jsonl")


class SchedulingTests(unittest.TestCase):
    def test_stage_assignment_order_and_effective_values(self):
        from thesis.recovery_successor_005 import run as pr

        tmp = tempfile.mkdtemp()
        try:
            World(tmp).build()
            table = pt.TargetTable(tmp, pt.build_table(tmp, models=MODELS), models=MODELS)
            enhanced = pr.stage_targets(table, "enhanced")
            self.assertEqual([t.is_base for t in enhanced], [True, True] + [False] * 8)
            self.assertEqual([t.variant for t in pr.stage_targets(table, "correctness")],
                             ["static_feedback"] * 3)
            self.assertEqual({t.variant for t in pr.stage_targets(table, "static.llov")}, {"test_feedback"})
            self.assertEqual([t.model_id for t in pr.stage_targets(table, "dynamic", models=["m_beta"])],
                             ["m_beta"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        config = load_config()
        values = pr.effective_values(config, "static.main")
        self.assertEqual(values["tools"]["value"], ["clang_tidy", "compiler", "cppcheck", "gcc_analyzer", "infer"])
        for flag in ("replace_tool_entries", "rerun_gaps", "replace_legacy_record"):
            self.assertEqual(values[flag], {"value": False, "source": "DEFAULT"})
        self.assertEqual(pr.effective_values(config, "correctness")["effective_run_timeout_seconds"]["source"], "CONFIG")
        with self.assertRaises(RecoveryRefused):
            pr.effective_values(config, "static.llov")


class RobustnessTests(unittest.TestCase):
    """Review fixes: signal semantics, provider isolation, per-target failure
    isolation, torn ledgers of other tools, tolerant status views."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.world = World(self.tmp).build()
        self.table = pt.TargetTable(self.tmp, pt.build_table(self.tmp, models=MODELS), models=MODELS)
        self.config = load_config()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_sigterm_is_a_graceful_stop(self):
        import signal

        from thesis.recovery_successor_005 import run as pr

        before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
        try:
            pr.install_signal_handlers()
            self.assertIs(signal.getsignal(signal.SIGINT), before[0])  # KeyboardInterrupt, as natively
            self.assertIsNot(signal.getsignal(signal.SIGTERM), before[1])
        finally:
            signal.signal(signal.SIGINT, before[0])
            signal.signal(signal.SIGTERM, before[1])
            pr.STOP_EVENT.clear()

    def test_provider_variables_never_reach_the_process(self):
        import os

        import thesis.config.load_config as loader

        names = pl.provider_environment(self.config)  # whatever an earlier load put there
        saved = dict(os.environ)
        try:
            key = next(m["api_key_env"] for m in self.config["models"] if m.get("api_key_env"))
            os.environ[key] = "secret"
            removed = pl.scrub_provider_environment(self.config)
            self.assertIn(key, removed)
            self.assertEqual(pl.provider_environment(self.config), [])
            pl.isolate_providers()
            self.assertIs(loader.load_dotenv(override=False), False)
            load_config()
            self.assertEqual(pl.provider_environment(self.config), [])
        finally:
            os.environ.clear()
            os.environ.update(saved)
        self.assertIsInstance(names, list)

    def test_a_target_failure_is_confined_to_its_target(self):
        from thesis.recovery_successor_005 import run as pr

        target = self.table.targets[0]
        open_items = []

        def broken():
            raise ValueError("native parser bug")

        self.assertEqual(pr._isolated("correctness", target, open_items, broken), {})
        self.assertEqual(open_items, ["correctness %s" % target.target_id])

        def refused():
            raise RecoveryRefused("foreign row")

        with self.assertRaises(pl.GlobalStop):
            pr._isolated("correctness", target, open_items, refused)

        def stopped():
            raise pl.GlobalStop("drift")

        with self.assertRaises(pl.GlobalStop):
            pr._isolated("correctness", target, open_items, stopped)

        def interrupted():
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            pr._isolated("correctness", target, open_items, interrupted)

    def test_status_reports_torn_ledgers_and_the_container_stage_archives_them(self):
        from unittest import mock

        from thesis.evaluation import successor_writer as sw
        from thesis.recovery_successor_005 import measure_static as ms
        from thesis.recovery_successor_005 import plan as pp
        from thesis.recovery_successor_005 import run as pr

        target = self.table.get("m_beta/full_ext_recovery_004__test_feedback__iter1")
        torn = self.world.write(pt.ledger_relative(target.model_id, target.source_run, "static.llov.jsonl"),
                                '{"sample_id": "x"')
        with self.assertRaises(pg.TornLedger):
            pp.plan(self.tmp, self.config, self.table, with_enhanced=False)
        lenient = pp.plan(self.tmp, self.config, self.table, with_enhanced=False, strict=False)
        self.assertTrue(any("torn" in finding for finding in lenient["integrity_findings"]))
        lock = sw.WriterLock(self.tmp, pl.SUCCESSOR, "test")
        token = lock.acquire()
        self.addCleanup(lock.release)

        class Authority:
            def __init__(self):
                self.token = token
                self.checks = 0

            def check(self):
                self.checks += 1
                return True

        calls = []
        with mock.patch.object(ms, "run_external", lambda *a, **k: calls.append(a[3].target_id) or 0):
            pr.run_stage("static.parcoach", self.tmp, self.config, self.table, Authority(), [target], [])
        self.assertEqual(torn.read_bytes(), b"")  # archived by the lock holder before planning
        self.assertTrue(torn.with_name(torn.name + ".torn").exists())
        self.assertEqual(calls, [target.target_id])


class IsolationAndProofTests(unittest.TestCase):
    def test_no_package_module_reaches_a_provider(self):
        from thesis.recovery_successor_005 import preflight as pf

        self.assertEqual(pf.provider_isolation(REPO_ROOT)["provider_paths"], 0)
        tmp = tempfile.mkdtemp()
        try:
            package = Path(tmp) / pf.PACKAGE_DIR
            package.mkdir(parents=True)
            (package / "bad.py").write_text("from thesis.generation import batch_api\n", encoding="utf-8")
            with self.assertRaises(RecoveryRefused):
                pf.provider_isolation(tmp)
            (package / "bad.py").write_text("from thesis.repair import orchestrator\n", encoding="utf-8")
            with self.assertRaises(RecoveryRefused):
                pf.provider_isolation(tmp)
            (package / "bad.py").write_text("import openai\n", encoding="utf-8")
            with self.assertRaises(RecoveryRefused):
                pf.provider_isolation(tmp)
            (package / "bad.py").write_text("def f(ra):\n    return ra.require_provider_call('x')\n",
                                            encoding="utf-8")
            with self.assertRaises(RecoveryRefused):
                pf.provider_isolation(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_measurement_equivalence_obligations(self):
        from thesis.recovery_successor_005 import equivalence as pe

        modules = sorted(set(pe.EQUIVALENCE_TESTS.values()))
        entry = OrderedDict([("label", "py312"), ("kind", "unittest"), ("status", "PASS"),
                             ("passed_test_modules", modules), ("evidence_path", "x.json")])
        result = pe.measurement_equivalence([entry])
        self.assertEqual(list(result), ["static", "correctness", "dynamic", "enhanced"])
        missing = OrderedDict(entry, passed_test_modules=modules[1:])
        with self.assertRaises(RecoveryRefused):
            pe.measurement_equivalence([missing])
        with self.assertRaises(RecoveryRefused):
            pe.measurement_equivalence([OrderedDict(entry, status="FAIL")])
        with self.assertRaises(RecoveryRefused):
            pe.measurement_equivalence([OrderedDict(entry, label="py38")])

    def test_phase2_sources_cover_the_package(self):
        from thesis.recovery_successor_005 import equivalence as pe

        package = sorted("thesis/recovery_successor_005/%s" % p.name
                         for p in (REPO_ROOT / "thesis/recovery_successor_005").glob("*.py"))
        self.assertEqual(sorted(s for s in pe.PHASE2_SOURCES if s.startswith("thesis/recovery_successor_005/")),
                         package)


if __name__ == "__main__":
    unittest.main()
