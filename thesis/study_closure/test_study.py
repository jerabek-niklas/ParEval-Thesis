"""Tests of the study sections (study.py) and the guarded composite
persistence (composite_closure.py) on synthetic data: the phase-2 synthetic
repository of thesis.recovery_successor_005.test_verify (a tiny pilot block
and a tiny full_ext block with complete phase-2 ledgers) for the composite,
the plan and the verification reports; fake definitions built with the
real hash rules for the definitions chain; hand-built summaries, logs and
reports for the pure helpers. The expensive real-repository checks
(lineage verification, composite over 5,460 cells) are not run here; one
read-only real-repository test runs only with STUDY_CLOSURE_REAL=1.

    python3 -B -m unittest -v thesis.study_closure.test_study
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest import mock

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt
from thesis.recovery_successor_005 import verify as pv
from thesis.recovery_successor_005.test_verify import (AUTHORIZATION, CONFIG, CONTRACT, EXPECTED_BINDING, MODEL,
                                                       PILOT_ITER, STATIC_RUN, TEST_RUN, SyntheticRepoTest,
                                                       write_jsonl)
from thesis.study_closure import composite_closure as cc
from thesis.study_closure import core
from thesis.study_closure import study
from thesis.study_closure.core import ClosureRefused, Section

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE2 = core.PHASE2


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def write_contracts(root):
    """Frozen contracts of the derived runs (as test_verify.CompositeTest)."""
    from thesis.evaluation import pilot_run_contract as prc

    for run in pc.DERIVED_RUNS:
        contract = OrderedDict([("schema_version", "run_contract.v1"), ("run_id", run), ("status", "READY")])
        contract["contract_sha256"] = prc.contract_sha256(contract)
        write_json(Path(root) / "thesis/evaluation/recovery" / run / "contract.json", contract)


def fake_summary(models=pl.MODELS, pilot=396, full_ext=1584, condition=None):
    """A census summary of the real shape (census.summary) for a complete study."""
    per_block = len(models) * len(pl.VARIANTS)
    blocks = OrderedDict()
    for block in pc.BLOCKS:
        blocks[block] = OrderedDict([
            ("terminal", per_block), ("loops", per_block), ("open", []), ("not_started", []),
            ("owners", OrderedDict([(core.PILOT if block == pc.PILOT_BLOCK else core.OWNERS[0], per_block)])),
            ("sample_states", OrderedDict([("stopped_clean", per_block)]))])
    return OrderedDict([
        ("total_repair_loops_done", "%d/%d" % (2 * per_block, 2 * per_block)),
        ("blocks", blocks),
        ("base_cells", OrderedDict([("pilot", pilot), ("full_ext", full_ext), ("total", pilot + full_ext)])),
        ("repair_conditions", [condition or sha("repair")])])


def fake_definitions(root, config_path):
    """The five phase-2 definitions with the real self-hash rules and chain."""
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.recovery_successor_005 import equivalence as pe
    from thesis.recovery_successor_005 import readiness as prd

    root = Path(root)
    defs = root / pl.DEFINITIONS_REL
    digest = sha("census")
    targets = OrderedDict([("schema_version", pt.SCHEMA), ("run_id", PHASE2), ("model_ids", list(pl.MODELS)),
                           ("census_digest", digest), ("target_count", 0), ("targets", [])])
    targets["table_sha256"] = canonical_sha256(targets)
    lineage = OrderedDict([("schema_version", pl.SCHEMA), ("run_id", PHASE2), ("profile", pl.PROFILE),
                           ("targets_sha256", targets["table_sha256"]), ("census_digest", digest)])
    lineage["lineage_sha256"] = pl.fingerprint(lineage)
    proof = OrderedDict([("schema_version", pe.SCHEMA), ("status", "PROVEN"), ("phase2_run_id", PHASE2)])
    proof["proof_sha256"] = canonical_sha256(proof)
    readiness = OrderedDict([("schema_version", prd.SCHEMA), ("gate", "READY"), ("run_id", PHASE2),
                             ("equivalence_sha256", proof["proof_sha256"]),
                             ("lineage_sha256", lineage["lineage_sha256"]), ("provider_calls", "NONE")])
    readiness["readiness_sha256"] = canonical_sha256(readiness)
    for name, document in (("targets.json", targets), ("lineage.json", lineage), ("equivalence.json", proof),
                           ("readiness.json", readiness)):
        write_json(defs / name, document)
    Path(config_path).write_text("profiles: {}\n", encoding="utf-8")
    provenance = OrderedDict([
        ("lineage_sha256", lineage["lineage_sha256"]), ("targets_sha256", targets["table_sha256"]),
        ("equivalence_sha256", proof["proof_sha256"]),
        ("readiness_lf_sha256", ch.lf_normalized_sha256(defs / "readiness.json")),
        ("config_lf_sha256", ch.lf_normalized_sha256(Path(config_path))),
        ("census_digest", digest), ("provider_calls", "NONE")])
    contract = OrderedDict([("schema_version", "pilot_run_contract.v3"), ("run_id", PHASE2), ("status", "READY"),
                            ("phase2_provenance", provenance)])
    contract["contract_sha256"] = prc.contract_sha256(contract)
    write_json(defs / "contract.json", contract)
    return OrderedDict([("targets", targets), ("lineage", lineage), ("proof", proof), ("readiness", readiness),
                        ("contract", contract)])


def rehashed_contract(contract):
    from thesis.evaluation import pilot_run_contract as prc

    contract = copy.deepcopy(contract)
    contract["contract_sha256"] = prc.contract_sha256(contract)
    return contract


def invocation_rows(stages=pl.STAGES, last=None):
    rows = []
    for stage in stages:
        for status in ("invoked", "completed"):
            rows.append(OrderedDict([("run_id", PHASE2), ("stage", stage), ("status", status),
                                     ("open_items", []), ("counts", {})]))
    if last:
        rows.append(OrderedDict([("run_id", PHASE2), ("stage", last[0]), ("status", last[1]),
                                 ("open_items", last[2])]))
    return rows


def fake_fragment(stage, model, run_id=PHASE2, outcome=None, scope=None):
    """An invocation fragment of the real shape (top-level run_id, content
    with run_id / stage / model_scope / invocation_sha256; outcome only on
    refused copies). The sha follows test_verify.FakeAuthority."""
    fragment = OrderedDict([("schema_version", "run_manifest_fragment.v1"), ("run_id", run_id), ("kind", "invocation"),
                            ("content", OrderedDict([("run_id", run_id), ("stage", stage),
                                                     ("model_scope", [model] if scope is None else scope),
                                                     ("invocation_sha256", sha("invocation:%s:%s" % (stage, model)))]))])
    if outcome is not None:
        fragment["outcome"] = outcome
    return fragment


def fragment_file_name(stage, model):
    """The real naming: dotted stages, a tool suffix on the static stages."""
    return "invocation.%s@%s%s" % (stage, model, "@tools-x.json" if stage.startswith("static.") else ".json")


def invocation_fragments_fake(models, stages=pl.STAGES):
    """name -> fragment for every (stage, model), as invocation_fragments reads them."""
    return OrderedDict((fragment_file_name(stage, model), fake_fragment(stage, model))
                       for stage in stages for model in models)


def write_phase2_run_state(root, models):
    """A finished phase-2 run in the results tree: complete manifest, the
    stage invocation log, and the manifest fragments (contract,
    authorization, per-stage runtime stamps, per (stage, model) invocation)
    whose recorded binding is test_verify.EXPECTED_BINDING."""
    results = Path(root) / core.PHASE2_RESULTS_REL
    write_json(results / "run_manifest.json", OrderedDict([
        ("run_id", PHASE2), ("complete", True), ("missing_expected_fragments", []), ("unexpected_fragments", [])]))
    write_jsonl(results / "phase2_stage_invocations.jsonl", invocation_rows())
    fragments = results / "run_manifest.fragments"
    write_json(fragments / "contract.json", OrderedDict([
        ("run_id", PHASE2), ("kind", "contract"), ("fingerprint_sha256", CONTRACT),
        ("content", OrderedDict([("contract_sha256", CONTRACT), ("contract", OrderedDict())]))]))
    write_json(fragments / "authorization.start.json", OrderedDict([
        ("run_id", PHASE2), ("kind", "authorization"), ("fingerprint_sha256", AUTHORIZATION),
        ("content", OrderedDict([("authorization_sha256", AUTHORIZATION)]))]))
    for stage in pl.STAGES:
        write_json(fragments / ("runtime.stage.%s.json" % stage), OrderedDict([
            ("run_id", PHASE2), ("kind", "runtime"),
            ("content", OrderedDict([("stage", stage), ("stage_runtime_sha256", sha("runtime:" + stage))]))]))
        for model in models:
            write_json(fragments / fragment_file_name(stage, model), fake_fragment(stage, model))
    return results


def minimal_composite(total=7, note="ünïcode"):
    document = OrderedDict([("schema_version", pc.SCHEMA), ("run_id", PHASE2),
                            ("cells", OrderedDict([("total", total)])), ("note", note)])
    document["composite_sha256"] = canonical_sha256(document)
    return document


# -- fixtures -------------------------------------------------------------------------------

class StudyFixture(SyntheticRepoTest):
    """The phase-2 synthetic repository plus the frozen contracts of the
    derived runs and an empty frozen spec file (the fixture's enhanced rows
    are build_benchmark_specs(benchmark, [], CONFIG), i.e. no LLM specs)."""

    def setUp(self):
        super().setUp()
        write_contracts(self.root)
        specs = self.root / "thesis/enhanced_tests/frozen/e3_final_specs.jsonl"
        specs.parent.mkdir(parents=True, exist_ok=True)
        specs.write_text("", encoding="utf-8")
        self.expected_population = OrderedDict([(core.PILOT, 2), (core.PARENT, 2)])

    def cells(self):
        return list(pc.iter_cells(self.root, CONFIG, self.repo.table, models=[MODEL]))

    def summary(self):
        return study.plan_summary(self.root, CONFIG, self.repo.table)

    def population(self):
        return OrderedDict([("source", pc.COMPOSITE_STUDY_REL), ("base_cells", pc.POPULATION_CELLS),
                            ("per_run", OrderedDict([(core.PARENT, pc.EXPECTED_POPULATION[core.PARENT]),
                                                     (core.PILOT, pc.EXPECTED_POPULATION[core.PILOT])]))])

    def document(self, cells=None, totals=None):
        totals = totals if totals is not None else self.summary()["totals"]
        cells = cells if cells is not None else self.cells()
        return pc.composite_document(self.root, CONFIG, self.repo.table, self.repo.lineage.sha256, totals,
                                     population=self.population(), cells=cells)


# -- history helpers -----------------------------------------------------------------------

class DefinitionsBoundTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="closure_defs_")
        self.root = Path(self._tmp)
        self.config_path = self.root / "phase2.yaml"
        self.defs = fake_definitions(self.root, self.config_path)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_chain_reproduces(self):
        facts = study.definitions_bound(self.root, self.config_path,
                                        table_sha=self.defs["targets"]["table_sha256"],
                                        lineage_sha=self.defs["lineage"]["lineage_sha256"])
        self.assertEqual(facts["lineage_sha256"], self.defs["lineage"]["lineage_sha256"])
        self.assertEqual(facts["targets_sha256"], self.defs["targets"]["table_sha256"])
        self.assertEqual(facts["proof_sha256"], self.defs["proof"]["proof_sha256"])
        self.assertEqual(facts["readiness_sha256"], self.defs["readiness"]["readiness_sha256"])
        self.assertEqual(facts["contract_sha256"], self.defs["contract"]["contract_sha256"])
        self.assertEqual(facts["census_digest"], sha("census"))
        self.assertEqual(facts["config_lf_sha256"], ch.lf_normalized_sha256(self.config_path))

    def test_loaded_table_or_lineage_must_match(self):
        with self.assertRaises(ClosureRefused):
            study.definitions_bound(self.root, self.config_path, table_sha="0" * 64)
        with self.assertRaises(ClosureRefused):
            study.definitions_bound(self.root, self.config_path, lineage_sha="0" * 64)

    def test_contract_bound_to_another_lineage_fails(self):
        contract = copy.deepcopy(self.defs["contract"])
        contract["phase2_provenance"]["lineage_sha256"] = "0" * 64
        write_json(self.root / pl.DEFINITIONS_REL / "contract.json", rehashed_contract(contract))
        with self.assertRaisesRegex(ClosureRefused, "provenance"):
            study.definitions_bound(self.root, self.config_path)

    def test_readiness_bound_to_another_lineage_fails(self):
        readiness = copy.deepcopy(self.defs["readiness"])
        readiness["lineage_sha256"] = "0" * 64
        readiness["readiness_sha256"] = canonical_sha256(OrderedDict(
            (k, v) for k, v in readiness.items() if k != "readiness_sha256"))
        write_json(self.root / pl.DEFINITIONS_REL / "readiness.json", readiness)
        with self.assertRaisesRegex(ClosureRefused, "readiness"):
            study.definitions_bound(self.root, self.config_path)

    def test_tampered_lineage_fails(self):
        lineage = copy.deepcopy(self.defs["lineage"])
        lineage["census_digest"] = "0" * 64
        write_json(self.root / pl.DEFINITIONS_REL / "lineage.json", lineage)
        with self.assertRaisesRegex(ClosureRefused, "self-hash"):
            study.definitions_bound(self.root, self.config_path)

    def test_changed_config_bytes_fail(self):
        self.config_path.write_text("profiles: {changed: true}\n", encoding="utf-8")
        with self.assertRaisesRegex(ClosureRefused, "provenance"):
            study.definitions_bound(self.root, self.config_path)

    def test_table_rederivation(self):
        ok, detail = study.table_rederivation(OrderedDict([("table_sha256", "a" * 64), ("target_count", 77)]), "a" * 64)
        self.assertTrue(ok)
        self.assertEqual(detail["target_count"], 77)
        self.assertFalse(study.table_rederivation(OrderedDict([("table_sha256", "b" * 64)]), "a" * 64)[0])
        self.assertFalse(study.table_rederivation(OrderedDict([("table_sha256", None)]), None)[0])


# -- population helpers --------------------------------------------------------------------

class CensusHelpersTest(unittest.TestCase):
    def test_complete_census_has_no_problem(self):
        summary = fake_summary()
        condition = summary["repair_conditions"][0]
        self.assertEqual(study.census_problems(summary, list(pl.MODELS)), [])
        self.assertEqual(study.census_problems(summary, list(pl.MODELS),
                                               repair_conditions=OrderedDict((run, condition) for run in core.RUNS)), [])
        self.assertEqual(summary["total_repair_loops_done"], "66/66")

    def test_census_negatives(self):
        summary = fake_summary()
        summary["blocks"]["full_ext"]["terminal"] -= 1
        summary["blocks"]["full_ext"]["open"] = ["m/static_feedback"]
        summary["total_repair_loops_done"] = "65/66"
        problems = study.census_problems(summary, list(pl.MODELS))
        self.assertTrue(any("65/66" in p for p in problems))
        self.assertTrue(any("open loops" in p for p in problems))
        self.assertTrue(study.census_problems(fake_summary(pilot=395), list(pl.MODELS)))
        summary = fake_summary()
        summary["repair_conditions"].append(sha("other"))
        self.assertTrue(any("exactly one" in p for p in study.census_problems(summary, list(pl.MODELS))))
        problems = study.census_problems(fake_summary(), list(pl.MODELS),
                                         repair_conditions=OrderedDict([(core.PILOT, sha("foreign"))]))
        self.assertTrue(any("differs from the census condition" in p for p in problems))
        # the loop count follows the model list, never a constant
        self.assertTrue(study.census_problems(fake_summary(), list(pl.MODELS)[:10]))

    def test_not_started_loops_fail(self):
        summary = fake_summary()
        summary["blocks"]["pilot"]["not_started"] = ["claude_fable_5/static_feedback"]
        problems = study.census_problems(summary, list(pl.MODELS))
        self.assertTrue(any("not started" in p for p in problems))

    def test_compact_summary_truncates_the_lists(self):
        summary = fake_summary()
        summary["blocks"]["full_ext"]["open"] = ["model_%d/static_feedback" % i for i in range(20)]
        compact = study.compact_census_summary(summary)
        self.assertEqual(len(compact["blocks"]["full_ext"]["open"]), study.EXAMPLES)
        self.assertEqual(compact["blocks"]["full_ext"]["open_count"], 20)
        self.assertEqual(compact["blocks"]["full_ext"]["not_started_count"], 0)
        self.assertEqual(compact["total_repair_loops_done"], summary["total_repair_loops_done"])
        self.assertEqual(compact["base_cells"], summary["base_cells"])
        # the summary itself is untouched (it is the cached census_summary)
        self.assertEqual(len(summary["blocks"]["full_ext"]["open"]), 20)
        self.assertTrue(any("open loops" in p for p in study.census_problems(summary, list(pl.MODELS))))
        self.assertEqual(study.compact_census_summary(OrderedDict()), OrderedDict())

    def test_provider_modules_loaded(self):
        from thesis.recovery_successor_004 import census  # noqa: F401 - the real census import chain

        self.assertEqual(study.provider_modules_loaded(), [])
        self.assertEqual(study.provider_modules_loaded({"openai": None, "json": None}), ["openai"])
        self.assertEqual(study.provider_modules_loaded({"google.genai.client": None}), ["google.genai"])
        self.assertEqual(study.provider_modules_loaded({"thesis.repair.run_repair": None}), ["thesis.repair.run_repair"])
        self.assertEqual(study.provider_modules_loaded({"openai_compat_helper": None}), [])
        self.assertNotIn("dotenv", study.FORBIDDEN_MODULES)
        self.assertNotIn("thesis.repair.orchestrator", study.FORBIDDEN_MODULES)

    def test_census_digest_rule(self):
        summary = fake_summary()
        self.assertEqual(study.census_digest(summary), canonical_sha256(summary))
        self.assertNotEqual(study.census_digest(summary), study.census_digest(fake_summary(pilot=395)))
        self.assertIn("census.summary", study.CENSUS_DIGEST_RULE)

    def test_derived_lineage_problems(self):
        entries = [OrderedDict([("run_id", run), ("base_cells", 0), ("contract_sha256", "c" * 64)])
                   for run in pc.DERIVED_RUNS]
        self.assertEqual(study.derived_lineage_problems(entries), [])
        owning = copy.deepcopy(entries)
        owning[0]["base_cells"] = 1
        self.assertTrue(any("base cell" in p for p in study.derived_lineage_problems(owning)))
        unbound = copy.deepcopy(entries)
        unbound[-1]["contract_sha256"] = None
        self.assertTrue(any("no frozen contract" in p for p in study.derived_lineage_problems(unbound)))
        self.assertTrue(study.derived_lineage_problems(entries[:-1]))


class CompositeFixtureTest(StudyFixture):
    def test_plan_is_empty_on_the_complete_fixture(self):
        summary = self.summary()
        self.assertEqual(study.plan_problems(summary), [])
        self.assertEqual(sorted(summary["totals"]), sorted(pl.STAGES))
        tampered = copy.deepcopy(summary)
        tampered["totals"]["enhanced"]["items"] = 1
        self.assertTrue(any("enhanced" in p for p in study.plan_problems(tampered)))
        tampered = copy.deepcopy(summary)
        tampered["integrity_findings"] = ["x: gap outside the assignment"]
        self.assertTrue(any("integrity" in p for p in study.plan_problems(tampered)))
        tampered = copy.deepcopy(summary)
        del tampered["totals"]["dynamic"]
        self.assertTrue(any("absent" in p for p in study.plan_problems(tampered)))
        tampered = copy.deepcopy(summary)
        tampered["totals"]["correctness"]["targets_open"] = 1
        self.assertTrue(any("correctness: 0 open item(s) in 1 target(s)" in p for p in study.plan_problems(tampered)))
        tampered = copy.deepcopy(summary)
        tampered["totals"]["bogus"] = OrderedDict([("items", 0), ("targets_open", 0)])
        self.assertTrue(any("outside the design: ['bogus']" in p for p in study.plan_problems(tampered)))

    def test_plan_fails_closed_on_a_missing_ledger(self):
        self.repo.ledger(TEST_RUN, "static.llov.jsonl").unlink()
        self.assertTrue(any("static.llov" in p for p in study.plan_problems(self.summary())))

    def test_composite_reconstruction_partition_and_owners(self):
        cells = self.cells()
        document = self.document(cells=cells)
        self.assertTrue(pc.verify_document(document))
        self.assertEqual(document["cells"]["total"], 7)
        pilot_expected = study.pilot_candidate_counts(self.root, [MODEL])
        self.assertEqual(pilot_expected, OrderedDict([(PILOT_ITER, 1)]))
        problems, detail = study.cells_partition(cells, self.repo.table, self.expected_population, pilot_expected)
        self.assertEqual(problems, [])
        self.assertEqual(detail["cells_total"], 7)
        self.assertEqual(detail["base_per_block"], OrderedDict([("pilot", 2), ("full_ext", 2)]))
        self.assertEqual(detail["candidates_per_block"], OrderedDict([("pilot", 1), ("full_ext", 2)]))
        self.assertEqual(detail["candidates_per_owner_run"],
                         OrderedDict([(STATIC_RUN, 1), (TEST_RUN, 1), (PILOT_ITER, 1)]))
        self.assertEqual((detail["pilot_block"], detail["full_ext_block"]), (3, 4))
        problems, detail = study.owner_problems(document["stage_coverage"], cells, self.repo.table)
        self.assertEqual(problems, [])
        self.assertEqual(detail["static_feedback_candidates"], 1)
        self.assertEqual(detail["phase2_static_supplements"], OrderedDict([("llov", 1), ("parcoach", 1)]))

    def test_partition_negatives(self):
        cells = self.cells()
        # the real population constants do not fit the fixture: the check is parametric
        problems, _ = study.cells_partition(cells, self.repo.table, pc.EXPECTED_POPULATION)
        self.assertTrue(any("base cells" in p for p in problems))
        duplicated = cells + [copy.deepcopy(cells[0])]
        problems, _ = study.cells_partition(duplicated, self.repo.table, self.expected_population)
        self.assertTrue(any("duplicate" in p for p in problems))
        excluded = copy.deepcopy(cells)
        excluded[-1]["source_run"] = core.EXCLUDED_RUNS[0]
        problems, _ = study.cells_partition(excluded, self.repo.table, self.expected_population)
        self.assertTrue(any("excluded run" in p for p in problems))
        drifted = copy.deepcopy(cells)
        drifted[-1]["source_sha256"] = "0" * 64
        problems, _ = study.cells_partition(drifted, self.repo.table, self.expected_population)
        self.assertTrue(any("not bound to a table target" in p for p in problems))
        problems, _ = study.cells_partition(cells, self.repo.table, self.expected_population,
                                            OrderedDict([(PILOT_ITER, 2)]))
        self.assertTrue(any("pilot candidates" in p for p in problems))
        third = copy.deepcopy(cells)
        third[0]["iteration"] = 3
        problems, _ = study.cells_partition(third, self.repo.table, self.expected_population)
        self.assertTrue(any("outside the repair design" in p for p in problems))
        # the owner field of a base cell and of a candidate is verified
        owned = copy.deepcopy(cells)
        base = [c for c in owned if c["iteration"] == 0][0]
        base["owner"] = core.OWNERS[0]
        problems, _ = study.cells_partition(owned, self.repo.table, self.expected_population)
        self.assertTrue(any("base cell owner %s" % core.OWNERS[0] in p for p in problems))
        owned = copy.deepcopy(cells)
        candidate = [c for c in owned if c["source_run"] == TEST_RUN][0]
        candidate["owner"] = core.PILOT
        problems, _ = study.cells_partition(owned, self.repo.table, self.expected_population)
        self.assertTrue(any("candidate owner pilot_002, expected %s" % TEST_RUN in p for p in problems))
        # a pilot-block candidate owned by a recovery run is outside the design
        misowned = copy.deepcopy(cells)
        pilot_candidate = [c for c in misowned if c["source_run"] == PILOT_ITER][0]
        pilot_candidate["source_run"] = TEST_RUN
        problems, _ = study.cells_partition(misowned, self.repo.table, self.expected_population)
        self.assertTrue(any("candidate of block pilot owned by %s" % core.OWNERS[0] in p for p in problems))

    def test_owner_negatives(self):
        cells = self.cells()
        coverage = self.document(cells=cells)["stage_coverage"]
        foreign = copy.deepcopy(coverage)
        foreign["full_ext"]["enhanced"]["owners"] = OrderedDict([(core.PARENT, 4)])
        problems, _ = study.owner_problems(foreign, cells, self.repo.table)
        self.assertTrue(any("enhanced owners" in p for p in problems))
        wrong = copy.deepcopy(coverage)
        wrong["full_ext"]["correctness"]["owners"][PHASE2] = 2
        problems, _ = study.owner_problems(wrong, cells, self.repo.table)
        self.assertTrue(any("phase 2 owns 2" in p for p in problems))
        incomplete = copy.deepcopy(coverage)
        incomplete["pilot"]["dynamic"]["with_evidence"] = 2
        problems, _ = study.owner_problems(incomplete, cells, self.repo.table)
        self.assertTrue(any("pilot dynamic" in p for p in problems))
        misplaced = copy.deepcopy(cells)
        for cell in misplaced:
            if cell["source_run"] == STATIC_RUN:
                cell["static"]["supplemented"]["llov"] = PHASE2
        problems, _ = study.owner_problems(coverage, misplaced, self.repo.table)
        self.assertTrue(any("phase-2 static supplement on a static_feedback" in p for p in problems))
        # a foreign supplement owner in the coverage, on a pilot cell, and a
        # foreign correctness owner
        foreign = copy.deepcopy(coverage)
        foreign["full_ext"]["static"]["supplemented_by"] = OrderedDict([(core.PILOT, 1)])
        problems, _ = study.owner_problems(foreign, cells, self.repo.table)
        self.assertTrue(any("static supplemented by ['pilot_002']" in p for p in problems))
        supplemented = copy.deepcopy(cells)
        pilot_cell = [c for c in supplemented if c["block"] == pc.PILOT_BLOCK][0]
        pilot_cell["static"]["supplemented"] = OrderedDict([("llov", core.OWNERS[1])])
        problems, _ = study.owner_problems(coverage, supplemented, self.repo.table)
        self.assertTrue(any("pilot cell %s supplemented by %s" % (pilot_cell["sample_id"], core.OWNERS[1]) in p
                            for p in problems))
        foreign_cell = copy.deepcopy(cells)
        full_cell = [c for c in foreign_cell if c["source_run"] == TEST_RUN][0]
        full_cell["static"]["supplemented"]["llov"] = "smoke_run"
        problems, _ = study.owner_problems(coverage, foreign_cell, self.repo.table)
        self.assertTrue(any("supplemented by smoke_run" in p for p in problems))
        foreign = copy.deepcopy(coverage)
        foreign["full_ext"]["correctness"]["owners"][core.PILOT] = 1
        problems, _ = study.owner_problems(foreign, cells, self.repo.table)
        self.assertTrue(any("correctness: foreign owners ['pilot_002']" in p for p in problems))

    def test_persisted_composite(self):
        document = self.document()
        ok, detail = study.persisted_composite(self.root, document, write_mode=False)
        self.assertTrue(ok)
        self.assertFalse(detail["persisted"])
        ok, detail = study.persisted_composite(self.root, document, write_mode=True)
        self.assertFalse(ok)
        path = pc.write_document(self.root, document)
        ok, detail = study.persisted_composite(self.root, document, write_mode=True)
        self.assertTrue(ok)
        self.assertEqual(detail["raw_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(detail["composite_sha256"], document["composite_sha256"])
        self.assertTrue(detail["bytes_identical"])
        # the same JSON in a foreign serialisation (CRLF): the dry run must
        # predict the --write outcome, which refuses it as a different composite
        write_phase2_run_state(self.root, [MODEL])
        path.write_bytes(cc.document_bytes(document).replace(b"\n", b"\r\n"))
        ok, detail = study.persisted_composite(self.root, document, write_mode=False)
        self.assertFalse(ok)
        self.assertTrue(detail["equal"])
        self.assertFalse(detail["bytes_identical"])
        with self.assertRaisesRegex(ClosureRefused, "different composite"):
            cc.composite_write_allowed(self.root, document)
        # a changed count with a recomputed hash is a different composite
        tampered = copy.deepcopy(document)
        tampered["cells"]["total"] = 8
        del tampered["composite_sha256"]
        tampered["composite_sha256"] = canonical_sha256(tampered)
        pc.write_document(self.root, tampered)
        ok, detail = study.persisted_composite(self.root, document)
        self.assertFalse(ok)
        self.assertFalse(detail["equal"])
        # a flipped byte without a recomputed hash fails closed (guard -> FAIL)
        data = path.read_bytes().replace(b'"total": 8', b'"total": 9')
        path.write_bytes(data)
        section = Section("population")
        self.assertFalse(section.guard("composite_persisted", study.persisted_composite, self.root, document))
        self.assertIn("RecoveryRefused", section.checks[0]["detail"])

    def test_derived_lineages_of_the_fixture(self):
        self.assertEqual(study.derived_lineage_problems(pc.derived_lineages(self.root)), [])

    def test_population_check_fails_closed_without_the_composite_study(self):
        section = Section("population")
        self.assertFalse(section.guard("base_cells_1980", study.population_check, self.root))
        self.assertEqual(section.status, core.FAIL)


# -- phase2 helpers --------------------------------------------------------------------------

class ReportsFixtureTest(StudyFixture):
    def persisted(self):
        result = self.repo.verify()
        pv.write_report(self.root, result)
        return result

    def test_reports_present_and_reproduce(self):
        self.persisted()
        loaded = study.load_reports(self.root, [MODEL])
        report, raw = loaded[MODEL]
        self.assertEqual(raw, core.raw_sha256(self.root, pv.report_relative(MODEL)))
        self.assertIn("written_at_utc", report)
        self.assertEqual(study.report_problems(report, MODEL, self.repo.lineage.sha256, self.repo.table.sha256,
                                               CONTRACT, AUTHORIZATION), [])
        ok, detail = study.reproduce_differences(report, self.repo.verify())
        self.assertTrue(ok)
        self.assertEqual((detail["differing_count"], detail["counts_equal"], detail["run_binding_equal"]),
                         (0, True, True))
        self.assertEqual(detail["checks"], len(report["checks"]))

    def test_report_problems(self):
        self.persisted()
        report = study.load_reports(self.root, [MODEL])[MODEL][0]
        problems = study.report_problems(report, MODEL, "0" * 64, self.repo.table.sha256, CONTRACT, AUTHORIZATION)
        self.assertTrue(any("lineage_sha256" in p for p in problems))
        problems = study.report_problems(report, MODEL, self.repo.lineage.sha256, self.repo.table.sha256,
                                         "0" * 64, AUTHORIZATION)
        self.assertTrue(any("contract" in p for p in problems))
        problems = study.report_problems(report, "claude_opus_5", self.repo.lineage.sha256, self.repo.table.sha256,
                                         CONTRACT, AUTHORIZATION)
        self.assertTrue(any("model_id" in p for p in problems))
        failing = copy.deepcopy(report)
        failing["status"] = pv.FAIL
        failing["model_complete"] = False
        self.assertEqual(len(study.report_problems(failing, MODEL, self.repo.lineage.sha256,
                                                   self.repo.table.sha256, CONTRACT, AUTHORIZATION)), 2)
        for key, value in (("schema_version", "phase2_model_verification.v0"), ("scope", "OTHER_SCOPE"),
                           ("run_id", core.OWNERS[3])):
            tampered = copy.deepcopy(report)
            tampered[key] = value
            problems = study.report_problems(tampered, MODEL, self.repo.lineage.sha256, self.repo.table.sha256,
                                             CONTRACT, AUTHORIZATION)
            self.assertEqual([p for p in problems if p.startswith(key + " is")], ["%s is %r, expected %r"
                                                                                    % (key, value, report[key])])
        problems = study.report_problems(report, MODEL, self.repo.lineage.sha256, "0" * 64, CONTRACT, AUTHORIZATION)
        self.assertTrue(any(p.startswith("targets_sha256 is") for p in problems))
        problems = study.report_problems(report, MODEL, self.repo.lineage.sha256, self.repo.table.sha256,
                                         CONTRACT, "0" * 64)
        self.assertEqual(problems, ["run_binding.authorization_sha256 differs from the run's authorization"])
        unstamped = copy.deepcopy(report)
        del unstamped["written_at_utc"]
        self.assertEqual(study.report_problems(unstamped, MODEL, self.repo.lineage.sha256, self.repo.table.sha256,
                                               CONTRACT, AUTHORIZATION), ["written_at_utc missing"])

    def test_reproduce_negatives(self):
        persisted = self.persisted()
        recomputed = self.repo.verify()
        mutated = copy.deepcopy(persisted)
        mutated["counts"]["full_ext"]["enhanced"]["rows"] += 1
        ok, detail = study.reproduce_differences(mutated, recomputed)
        self.assertFalse(ok)
        self.assertFalse(detail["counts_equal"])
        mutated = copy.deepcopy(persisted)
        mutated["checks"][3]["detail"]["samples"] = 99
        ok, detail = study.reproduce_differences(mutated, recomputed)
        self.assertFalse(ok)
        self.assertEqual(detail["differing_checks"], [persisted["checks"][3]["check"]])
        mutated = copy.deepcopy(persisted)
        mutated["run_binding"]["contract_sha256"] = "0" * 64
        self.assertFalse(study.reproduce_differences(mutated, recomputed)[0])
        # a persisted FAIL never 'reproduces', even with identical checks
        stale = copy.deepcopy(persisted)
        stale["status"] = pv.FAIL
        stale["model_complete"] = False
        ok, detail = study.reproduce_differences(stale, recomputed)
        self.assertFalse(ok)
        self.assertEqual((detail["persisted_status"], detail["persisted_model_complete"]), (pv.FAIL, False))
        self.assertEqual((detail["status"], detail["differing_count"], detail["counts_equal"]), (pv.PASS, 0, True))
        # a recomputed FAIL never reproduces a PASS
        self.repo.ledger(TEST_RUN, "static.llov.jsonl").unlink()
        failing = self.repo.verify()
        ok, detail = study.reproduce_differences(persisted, failing)
        self.assertFalse(ok)
        self.assertEqual(detail["status"], pv.FAIL)
        self.assertTrue(detail["differing_checks"])

    def test_missing_report_refuses(self):
        self.persisted()
        (self.root / pv.report_relative(MODEL)).unlink()
        with self.assertRaises(ClosureRefused):
            study.load_reports(self.root, [MODEL])

    def test_enhanced_totals(self):
        result = self.repo.verify()
        coverage = self.document()["stage_coverage"]
        problems, detail = study.enhanced_totals(OrderedDict([(MODEL, result)]), coverage)
        self.assertEqual(problems, [])
        self.assertEqual((detail["pilot_pairs"], detail["full_ext_pairs"], detail["total"]), (60, 80, 140))
        mutated = copy.deepcopy(result)
        mutated["counts"]["pilot"]["enhanced"]["rows"] = 61
        problems, _ = study.enhanced_totals(OrderedDict([(MODEL, mutated)]), coverage)
        self.assertTrue(any("60 expected pairs, 61 rows" in p for p in problems))
        wrong = copy.deepcopy(coverage)
        wrong["full_ext"]["enhanced"]["pairs"] = 79
        problems, _ = study.enhanced_totals(OrderedDict([(MODEL, result)]), wrong)
        self.assertTrue(any("composite pairs 79" in p for p in problems))
        self.assertTrue(study.enhanced_totals(OrderedDict(), coverage)[0])

    def test_ledger_hygiene_and_registration(self):
        result = self.repo.verify()
        reports = OrderedDict([(MODEL, result)])
        problems, detail = study.ledger_hygiene(reports)
        self.assertEqual(problems, [])
        self.assertEqual((detail["stray"], detail["archived_torn_tails"], detail["repeated_build_groups"]), (0, 0, 0))
        stray = self.root / pt.ledger_relative(MODEL, core.EXCLUDED_RUNS[0], "static.llov.jsonl")
        write_jsonl(stray, [])
        torn = self.repo.ledger(TEST_RUN, pt.ENHANCED_FILE + ".torn")
        torn.write_text("{}\n", encoding="utf-8")
        problems, detail = study.ledger_hygiene(OrderedDict([(MODEL, self.repo.verify())]))
        self.assertTrue(any("stray" in p for p in problems))
        self.assertEqual(detail["archived_torn_tails"], 1)
        self.assertTrue(study.ledger_hygiene(OrderedDict())[0])
        self.assertTrue(study.ledger_hygiene(OrderedDict([(MODEL, OrderedDict([("checks", [])]))]))[0])
        # a temporary file is a failure (stricter than the spec's stray-only rule)
        temporary = copy.deepcopy(result)
        bound = [c for c in temporary["checks"] if c["check"] == "full_ext:phase2_ledgers_bound_to_targets"][0]
        bound["detail"]["temporary_files"] = ["x.jsonl.tmp-1"]
        problems, detail = study.ledger_hygiene(OrderedDict([(MODEL, temporary)]))
        self.assertEqual(problems, ["%s: temporary files ['x.jsonl.tmp-1']" % MODEL])
        self.assertEqual(detail["temporary_files"], 1)
        # verify.py's string detail of a model without a supplements dir is a
        # valid PASS state; the same string on a FAIL is not
        bare = OrderedDict([("checks", [OrderedDict([("check", "full_ext:phase2_ledgers_bound_to_targets"),
                                                     ("status", pv.PASS), ("detail", study.NO_LEDGERS_DETAIL)])])])
        problems, detail = study.ledger_hygiene(OrderedDict([(MODEL, bare)]))
        self.assertEqual(problems, [])
        self.assertEqual(detail["per_model"][MODEL]["stray"], 0)
        bare["checks"][0]["status"] = pv.FAIL
        self.assertEqual(study.ledger_hygiene(OrderedDict([(MODEL, bare)]))[0],
                         ["%s: no phase2_ledgers_bound_to_targets detail" % MODEL])
        problems, detail = study.invocations_registered(copy.deepcopy(EXPECTED_BINDING), reports)
        self.assertEqual(problems, [])
        self.assertEqual(detail["invocations_per_stage"], OrderedDict((s, 1) for s in pl.STAGES))
        binding = copy.deepcopy(EXPECTED_BINDING)
        binding["invocation_sha256"]["dynamic"] = []
        self.assertTrue(any("dynamic: no invocation_sha256" in p
                            for p in study.invocations_registered(binding, reports)[0]))
        self.assertTrue(study.invocations_registered(None, reports)[0])
        unbound = copy.deepcopy(result)
        del unbound["run_binding"]["invocation_sha256"]["enhanced"]
        self.assertTrue(any("report invocation_sha256 empty" in p for p in
                            study.invocations_registered(copy.deepcopy(EXPECTED_BINDING),
                                                         OrderedDict([(MODEL, unbound)]))[0]))
        unstamped = copy.deepcopy(result)
        unstamped["run_binding"]["stage_runtime_sha256"]["dynamic"] = []
        self.assertEqual(study.invocations_registered(copy.deepcopy(EXPECTED_BINDING),
                                                      OrderedDict([(MODEL, unstamped)]))[0],
                         ["%s: report stage_runtime_sha256 empty for ['dynamic']" % MODEL])


class StageHistoryTest(unittest.TestCase):
    MODELS = ("claude_fable_5", "qwen37_max")

    def fragments(self):
        return invocation_fragments_fake(self.MODELS)

    def test_completed_history(self):
        problems, detail = study.stage_history(invocation_rows(), self.fragments(), list(self.MODELS))
        self.assertEqual(problems, [])
        self.assertEqual(detail["interrupted_invocations"], 0)
        self.assertEqual(detail["fragments"], len(pl.STAGES) * len(self.MODELS))
        for stage in pl.STAGES:
            self.assertEqual(detail["stages"][stage]["invocation_fragments"], 2)
            self.assertEqual(detail["stages"][stage]["last_status"], "completed")

    def test_interrupted_invocation_is_counted_not_failed(self):
        rows = invocation_rows()
        extra = OrderedDict([("run_id", PHASE2), ("stage", "dynamic"), ("status", "invoked"), ("open_items", [])])
        rows.insert(rows.index([r for r in rows if r["stage"] == "dynamic"][0]), extra)
        problems, detail = study.stage_history(rows, self.fragments(), list(self.MODELS))
        self.assertEqual(problems, [])
        self.assertEqual(detail["interrupted_invocations"], 1)
        self.assertEqual(detail["stages"]["dynamic"]["invoked"], 2)

    def test_last_status_invoked_fails(self):
        rows = invocation_rows(last=("enhanced", "invoked", []))
        problems, detail = study.stage_history(rows, self.fragments(), list(self.MODELS))
        self.assertTrue(any("enhanced: last invocation 'invoked'" in p for p in problems))
        self.assertEqual(detail["interrupted_invocations"], 1)
        rows = invocation_rows(last=("enhanced", "completed", ["x"]))
        self.assertTrue(study.stage_history(rows, self.fragments(), list(self.MODELS))[0])
        # a status outside invoked/completed is counted and, as the last row, fails
        rows = invocation_rows(last=("correctness", "aborted", []))
        problems, detail = study.stage_history(rows, self.fragments(), list(self.MODELS))
        self.assertTrue(any("correctness: last invocation 'aborted'" in p for p in problems))
        self.assertEqual(detail["stages"]["correctness"]["other"], 1)

    def test_missing_fragment_or_stage_fails(self):
        fragments = self.fragments()
        del fragments[fragment_file_name("static.main", "qwen37_max")]
        problems, _ = study.stage_history(invocation_rows(), fragments, list(self.MODELS))
        self.assertEqual(problems, ["no invocation fragment for static.main@qwen37_max"])
        # a model name that is a prefix of another never matches the other's fragment
        problems, _ = study.stage_history(invocation_rows(), invocation_fragments_fake(("claude_fable_5x",)),
                                          ["claude_fable_5"])
        self.assertEqual(len([p for p in problems if p.startswith("no invocation fragment")]), len(pl.STAGES))
        self.assertTrue(any("outside the study" in p for p in problems))
        rows = [r for r in invocation_rows() if r["stage"] != "static.llov"]
        self.assertTrue(any("static.llov" in p for p in study.stage_history(rows, self.fragments(),
                                                                             list(self.MODELS))[0]))
        foreign = invocation_rows()
        foreign[0]["run_id"] = "other"
        self.assertTrue(any("foreign" in p for p in study.stage_history(foreign, self.fragments(),
                                                                         list(self.MODELS))[0]))
        unknown = invocation_rows()
        unknown.append(OrderedDict([("run_id", PHASE2), ("stage", "bogus"), ("status", "completed"), ("open_items", [])]))
        self.assertTrue(any("unknown stage 'bogus'" in p for p in study.stage_history(unknown, self.fragments(),
                                                                                       list(self.MODELS))[0]))

    def test_fragment_content_is_verified(self):
        name = fragment_file_name("dynamic", "qwen37_max")
        models = list(self.MODELS)

        def problems_with(mutate):
            fragments = self.fragments()
            mutate(fragments)
            return study.stage_history(invocation_rows(), fragments, models)[0]

        def wrong_stage(f):
            f[name]["content"]["stage"] = "enhanced"

        def foreign_scope(f):
            f[name]["content"]["model_scope"] = ["claude_fable_5"]

        def refused(f):
            f[name]["outcome"] = "REFUSED"

        def other_run(f):
            f[name]["content"]["run_id"] = core.OWNERS[3]

        def foreign_model(f):
            f["invocation.enhanced@foreign_model.json"] = fake_fragment("enhanced", "foreign_model")

        def foreign_stage(f):
            f["invocation.bogus@claude_fable_5.json"] = fake_fragment("bogus", "claude_fable_5")

        def unreadable(f):
            f[name] = None

        self.assertEqual(problems_with(wrong_stage), ["%s: content stage 'enhanced', expected dynamic" % name])
        self.assertEqual(problems_with(foreign_scope), ["%s: qwen37_max not in model_scope ['claude_fable_5']" % name])
        self.assertEqual(problems_with(refused), ["%s: refused registration" % name])
        self.assertEqual(problems_with(other_run), ["%s: not a phase-2 fragment (run_id 'full_ext_phase2_001'/%r)"
                                                    % (name, core.OWNERS[3])])
        self.assertEqual(problems_with(foreign_model),
                         ["invocation fragment(s) outside the study: ['invocation.enhanced@foreign_model.json']"])
        self.assertEqual(problems_with(foreign_stage),
                         ["invocation fragment(s) outside the study: ['invocation.bogus@claude_fable_5.json']"])
        self.assertEqual(problems_with(unreadable), ["%s: unreadable fragment" % name])
        self.assertEqual(study.fragment_identity("invocation.static.main@claude_fable_5@tools-main.json"),
                         ("static.main", "claude_fable_5"))
        self.assertEqual(study.fragment_identity("invocation.enhanced@qwen37_max.json"), ("enhanced", "qwen37_max"))

    def test_invocation_fragments_reads_the_current_fragments_only(self):
        tmp = tempfile.mkdtemp(prefix="closure_fragments_")
        try:
            root = Path(tmp)
            with self.assertRaisesRegex(ClosureRefused, "missing artifact"):
                study.invocation_fragments(root)
            directory = root / study.FRAGMENTS_REL
            name = fragment_file_name("enhanced", "qwen37_max")
            write_json(directory / name, fake_fragment("enhanced", "qwen37_max"))
            write_json(directory / "history" / fragment_file_name("enhanced", "claude_fable_5"),
                       fake_fragment("enhanced", "claude_fable_5", outcome="REFUSED"))
            write_json(directory / "runtime.stage.enhanced.json", OrderedDict([("run_id", PHASE2)]))
            write_json(directory / "contract.json", OrderedDict([("run_id", PHASE2)]))
            fragments = study.invocation_fragments(root)
            self.assertEqual(list(fragments), [name])
            self.assertEqual(fragments[name]["content"]["model_scope"], ["qwen37_max"])
            self.assertIn("runtime.stage.enhanced.json", study.fragment_names(root))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# -- composite_closure ---------------------------------------------------------------------

class CompositeClosureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="closure_composite_")
        self.root = Path(self._tmp)
        self.results = self.root / core.PHASE2_RESULTS_REL
        self.manifest(complete=True)
        write_jsonl(self.results / "phase2_stage_invocations.jsonl", invocation_rows())
        self.document = minimal_composite()
        self.path = self.root / core.COMPOSITE_REL

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def manifest(self, run_id=PHASE2, complete=True, missing=(), unexpected=()):
        write_json(self.results / "run_manifest.json", OrderedDict([
            ("run_id", run_id), ("complete", complete), ("missing_expected_fragments", list(missing)),
            ("unexpected_fragments", list(unexpected))]))

    def test_write_allowed_facts(self):
        facts = cc.composite_write_allowed(self.root)
        self.assertEqual((facts["exists"], facts["identical"], facts["writer_locks"]), (False, None, []))
        self.assertEqual((facts["missing_expected_fragments"], facts["unexpected_fragments"]), ([], []))
        self.assertEqual(facts["stages_completed"], list(pl.STAGES))
        self.assertEqual(cc.last_stage_status(invocation_rows())["enhanced"]["status"], "completed")

    def test_persist_is_deterministic_and_idempotent(self):
        first = cc.persist_composite(self.root, self.document)
        path = self.path
        self.assertTrue(first["written"])
        self.assertEqual(path.read_bytes(), cc.document_bytes(self.document))
        self.assertEqual(first["raw_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual((first["composite_sha256"], first["bytes"]),
                         (self.document["composite_sha256"], len(path.read_bytes())))
        second = cc.persist_composite(self.root, self.document)
        self.assertFalse(second["written"])
        self.assertEqual(second["raw_sha256"], first["raw_sha256"])
        self.assertTrue(cc.composite_write_allowed(self.root, self.document)["identical"])
        self.assertFalse(sw.lock_path(self.root, PHASE2).exists())
        # the serialisation is the writer's: a second atomic write gives the same bytes
        pc.write_document(self.root, self.document)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), first["raw_sha256"])

    def test_refusals(self):
        with self.assertRaisesRegex(ClosureRefused, "persists only"):
            cc.composite_write_allowed(self.root, relative="thesis/results/intermediate/pilot_002/x.json")
        lock = sw.WriterLock(self.root, core.OWNERS[3], "test")
        lock.acquire()
        try:
            with self.assertRaisesRegex(ClosureRefused, "writer lock"):
                cc.composite_write_allowed(self.root)
            with self.assertRaisesRegex(ClosureRefused, "writer lock"):
                cc.persist_composite(self.root, self.document)
        finally:
            lock.release()
        self.assertFalse(self.path.exists())
        # a phase-2 lock that is not ours refuses with the lock NAME only
        # (never successor_writer's message with the absolute path and pid)
        own = sw.WriterLock(self.root, PHASE2, "test")
        own.acquire()
        try:
            with self.assertRaises(ClosureRefused) as refused:
                cc.persist_composite(self.root, self.document)
            self.assertIn("writer lock", str(refused.exception))
            self.assertIn(own.path.name, str(refused.exception))
            self.assertNotIn(str(self.root), str(refused.exception))
            self.assertNotIn("pid", str(refused.exception))
        finally:
            own.release()
        self.assertFalse(self.path.exists())
        cc.persist_composite(self.root, self.document)
        with self.assertRaisesRegex(ClosureRefused, "different composite"):
            cc.persist_composite(self.root, minimal_composite(total=8))
        with self.assertRaisesRegex(ClosureRefused, "different composite"):
            cc.composite_write_allowed(self.root, minimal_composite(total=8))
        self.assertEqual(self.path.read_bytes(), cc.document_bytes(self.document))
        broken = copy.deepcopy(self.document)
        broken["cells"]["total"] = 99
        with self.assertRaises(Exception):
            cc.persist_composite(self.root, broken)

    def test_lock_race_refuses_with_the_lock_name(self):
        """A lock that appears between the guard and the acquire (another
        writer) is reported by name, without the absolute path / pid / time."""
        message = "another successor writer holds %s (pid 1 on host since 2026-10-17)" % sw.lock_path(self.root, PHASE2)
        with mock.patch.object(sw.WriterLock, "acquire", side_effect=RecoveryRefused(message)):
            with self.assertRaises(ClosureRefused) as refused:
                cc.persist_composite(self.root, self.document)
        self.assertEqual(str(refused.exception), "successor writer lock present: " + sw.lock_path(self.root, PHASE2).name)
        self.assertFalse(self.path.exists())
        self.assertFalse(sw.lock_path(self.root, PHASE2).exists())

    def test_own_lock_must_carry_our_token(self):
        own = sw.WriterLock(self.root, PHASE2, "test")
        own.acquire()
        try:
            facts = cc.composite_write_allowed(self.root, own_lock=own)
            self.assertEqual(facts["writer_locks"], [own.path.name])
            stale = types.SimpleNamespace(path=own.path, token="not-the-token")
            with self.assertRaisesRegex(ClosureRefused, "own writer lock is not held"):
                cc.composite_write_allowed(self.root, own_lock=stale)
            unheld = types.SimpleNamespace(path=own.path, token=None)
            with self.assertRaisesRegex(ClosureRefused, "writer lock"):
                cc.composite_write_allowed(self.root, own_lock=unheld)
        finally:
            own.release()

    def test_persist_hook_runs_only_in_write_mode(self):
        calls = []
        hook = lambda document: calls.append(document["composite_sha256"]) or OrderedDict([("written", True)])  # noqa: E731
        dry = types.SimpleNamespace(options=OrderedDict([("write", False), ("persist_composite", hook)]))
        self.assertIsNone(study.persist_if_requested(dry, self.document))
        unhooked = types.SimpleNamespace(options=OrderedDict([("write", True)]))
        self.assertIsNone(study.persist_if_requested(unhooked, self.document))
        self.assertEqual(calls, [])
        formal = types.SimpleNamespace(options=OrderedDict([("write", True), ("persist_composite", hook)]))
        self.assertEqual(study.persist_if_requested(formal, self.document), OrderedDict([("written", True)]))
        self.assertEqual(calls, [self.document["composite_sha256"]])
        # the real hook target: persist under the lock, then the persisted check agrees
        formal.options["persist_composite"] = lambda document: cc.persist_composite(self.root, document)
        self.assertTrue(study.persist_if_requested(formal, self.document)["written"])
        self.assertTrue(study.persisted_composite(self.root, self.document, write_mode=True)[0])

    def test_persisted_check_gates_the_write_on_the_preceding_checks(self):
        """Regression: --write never materialises the composite of a failed
        closure (a drifted tree with FAILing history/population checks)."""
        calls = []

        def hook(document):
            calls.append(document["composite_sha256"])
            return cc.persist_composite(self.root, document)

        formal = types.SimpleNamespace(root=self.root, options=OrderedDict([("write", True), ("persist_composite", hook)]))
        blocking = ["history:phase2_lineage_verify", "population:composite_cells_partition"]
        ok, detail = study.persisted_check(formal, self.document, blocking, write_mode=True)
        self.assertFalse(ok)
        self.assertEqual(calls, [])
        self.assertFalse(self.path.exists())
        self.assertEqual((detail["persisted"], detail["note"]), (False, "not persisted: preceding checks failed"))
        self.assertEqual((detail["failing"], detail["failing_count"]), (blocking, 2))
        self.assertEqual(detail["composite_sha256"], self.document["composite_sha256"])
        self.assertEqual(detail["persist"]["persisted"], False)
        # dry run with failing preceding checks: nothing persisted, the comparison still runs
        dry = types.SimpleNamespace(root=self.root, options=OrderedDict([("write", False), ("persist_composite", hook)]))
        ok, detail = study.persisted_check(dry, self.document, blocking, write_mode=False)
        self.assertTrue(ok)
        self.assertFalse(detail["persisted"])
        self.assertEqual(detail["persist"]["note"], "not persisted: preceding checks failed")
        self.assertEqual(calls, [])
        # every preceding check passed: the hook persists and the comparison agrees
        ok, detail = study.persisted_check(formal, self.document, [], write_mode=True)
        self.assertTrue(ok)
        self.assertTrue(detail["persisted"])
        self.assertTrue(detail["bytes_identical"])
        self.assertTrue(detail["persist"]["written"])
        self.assertEqual(calls, [self.document["composite_sha256"]])
        self.assertEqual(self.path.read_bytes(), cc.document_bytes(self.document))
        # the blockers are the failing checks of the given sections, in order
        passed, failed = Section("history"), Section("population")
        passed.add("ok", True)
        failed.add("bad", False)
        failed.add("fine", True)
        failed.add("worse", False)
        self.assertEqual(study.persist_blockers(passed, failed), ["population:bad", "population:worse"])
        self.assertEqual(study.persist_blockers(passed), [])

    def test_run_state_guards(self):
        self.manifest(complete=False)
        with self.assertRaisesRegex(ClosureRefused, "not complete"):
            cc.composite_write_allowed(self.root)
        self.manifest(run_id="other")
        with self.assertRaisesRegex(ClosureRefused, "not complete"):
            cc.composite_write_allowed(self.root)
        # a contradictory manifest (complete with missing/unexpected fragments) is refused
        self.manifest(missing=["invocation.enhanced@qwen37_max.json"])
        with self.assertRaisesRegex(ClosureRefused, "missing fragments \\['invocation.enhanced@qwen37_max.json'\\]"):
            cc.composite_write_allowed(self.root)
        self.manifest(unexpected=["stray.json"])
        with self.assertRaisesRegex(ClosureRefused, "unexpected fragments \\['stray.json'\\]"):
            cc.composite_write_allowed(self.root)
        write_json(self.results / "run_manifest.json", OrderedDict([("run_id", PHASE2), ("complete", True)]))
        with self.assertRaisesRegex(ClosureRefused, "missing fragments None"):
            cc.composite_write_allowed(self.root)
        self.manifest()
        self.assertTrue(cc.composite_write_allowed(self.root)["manifest_complete"])
        write_jsonl(self.results / "phase2_stage_invocations.jsonl", invocation_rows(last=("enhanced", "invoked", [])))
        with self.assertRaisesRegex(ClosureRefused, "enhanced"):
            cc.composite_write_allowed(self.root)
        write_jsonl(self.results / "phase2_stage_invocations.jsonl",
                    [r for r in invocation_rows() if r["stage"] != "correctness"])
        with self.assertRaisesRegex(ClosureRefused, "correctness"):
            cc.composite_write_allowed(self.root)
        # a row of an unknown stage is refused (fail-closed, as study.stage_history)
        write_jsonl(self.results / "phase2_stage_invocations.jsonl", invocation_rows() + [OrderedDict([
            ("run_id", PHASE2), ("stage", "bogus"), ("status", "invoked"), ("open_items", [])])])
        with self.assertRaisesRegex(ClosureRefused, "unknown stage 'bogus'"):
            cc.composite_write_allowed(self.root)
        (self.results / "phase2_stage_invocations.jsonl").unlink()
        with self.assertRaisesRegex(ClosureRefused, "missing artifact"):
            cc.composite_write_allowed(self.root)
        with self.assertRaises(ClosureRefused):
            cc.last_stage_status([OrderedDict([("run_id", "other"), ("stage", "enhanced"), ("status", "completed")])])
        with self.assertRaisesRegex(ClosureRefused, "unknown stage"):
            cc.last_stage_status([OrderedDict([("run_id", PHASE2), ("stage", "bogus"), ("status", "invoked")])])


# -- collect over the fixture ------------------------------------------------------------------

class CollectFixtureTest(StudyFixture):
    """study.collect over the synthetic repository (plus a finished phase-2
    run state and the persisted report of its one model): the section names,
    every check id, every cache key and every data field report.py reads.
    The anchors of the real repository (custody, definitions, the frozen
    census digest, the composite study, the population constants) cannot be
    satisfied by the fixture: those checks are asserted FAIL by id."""

    EXPECTED_CHECKS = OrderedDict([
        ("history", ["phase2_lineage_verify", "custody_chain", "phase2_definitions_bound", "target_table_rederives"]),
        ("population", ["census_66_66", "census_digest_frozen", "base_cells_1980", "derived_lineages_own_no_base_cells",
                        "composite_reconstruction", "composite_cells_partition", "composite_owners",
                        "composite_persisted"]),
        ("phase2", ["plan_empty", "reports_present", "reports_reproduce", "enhanced_pairs_total", "stage_history",
                    "ledger_hygiene", "manifest_invocations_registered"]),
    ])
    CACHE_KEYS = ("lineage_verify", "census", "census_summary", "population", "plan_summary", "composite_cells",
                  "composite_document", "phase2_reports", "phase2_verify")
    FIXTURE_FAILING = ["history:custody_chain", "history:phase2_definitions_bound", "history:target_table_rederives",
                       "population:census_66_66", "population:census_digest_frozen", "population:base_cells_1980",
                       "population:composite_cells_partition", "phase2:reports_reproduce"]

    def context(self, write=False, hook=None):
        pv.write_report(self.root, self.repo.verify())
        write_phase2_run_state(self.root, [MODEL])
        lineage = types.SimpleNamespace(sha256=self.repo.lineage.sha256, targets_sha256=self.repo.table.sha256,
                                        document=OrderedDict([("protected", OrderedDict()), ("census_digest", "0" * 64)]),
                                        verify=self.repo.lineage.verify)
        options = OrderedDict([("write", write)])
        if hook is not None:
            options["persist_composite"] = hook
        binding = OrderedDict([("contract_sha256", CONTRACT), ("authorization_sha256", AUTHORIZATION),
                               ("manifest_complete", True), ("runtime", OrderedDict([("repair_cond", sha("repair"))]))])
        cache = OrderedDict([("run_bindings", OrderedDict([(PHASE2, binding)])), ("population", self.population())])
        return types.SimpleNamespace(root=self.root, config=CONFIG, config_path=str(self.root / "phase2.yaml"),
                                     options=options, cache=cache, lineage=lineage, table=self.repo.table,
                                     timed=lambda key, function, *a, **kw: function(*a, **kw), log=lambda m: None,
                                     timings=[])

    @staticmethod
    def checks_of(sections):
        return OrderedDict((c["check"], c) for s in sections for c in s.checks)

    def test_collect_ids_cache_keys_and_data(self):
        ctx = self.context()
        sections = study.collect(ctx, models=[MODEL])
        self.assertEqual([s.name for s in sections], list(study.SECTIONS))
        for section in sections:
            self.assertEqual([c["check"] for c in section.checks],
                             ["%s:%s" % (section.name, i) for i in self.EXPECTED_CHECKS[section.name]])
        failing = [c["check"] for s in sections for c in s.checks if c["status"] != core.PASS]
        self.assertEqual(failing, self.FIXTURE_FAILING)
        for key in self.CACHE_KEYS:
            self.assertIsNotNone(ctx.cache.get(key), key)
        self.assertEqual(ctx.cache["lineage_verify"]["status"], core.PASS)
        self.assertEqual(ctx.cache["census_summary"]["total_repair_loops_done"], "0/6")
        self.assertEqual(sorted(ctx.cache["plan_summary"]["totals"]), sorted(pl.STAGES))
        self.assertEqual(len(ctx.cache["composite_cells"]), 7)
        self.assertEqual(ctx.cache["composite_document"]["cells"]["total"], 7)
        self.assertEqual(list(ctx.cache["phase2_reports"]), [MODEL])
        self.assertEqual(list(ctx.cache["phase2_verify"]), [MODEL])
        history, population, phase2 = sections
        self.assertEqual(history.data["lineage_sha256"], self.repo.lineage.sha256)
        self.assertEqual(history.data["targets_sha256"], self.repo.table.sha256)
        composite = population.data["composite"]
        self.assertEqual(list(composite), ["relative", "persisted", "raw_sha256", "composite_sha256"])
        self.assertEqual((composite["relative"], composite["persisted"], composite["raw_sha256"]),
                         (core.COMPOSITE_REL, False, None))
        self.assertEqual(composite["composite_sha256"], ctx.cache["composite_document"]["composite_sha256"])
        self.assertIs(population.data["census_summary"], ctx.cache["census_summary"])
        self.assertEqual(population.data["cells"]["total"], 7)
        self.assertEqual(phase2.data["enhanced_pairs"], OrderedDict([("pilot", 60), ("full_ext", 80), ("total", 140)]))
        self.assertEqual(phase2.data["incidents"], OrderedDict([("archived_torn_tails", 0), ("repeated_build_groups", 0),
                                                                ("interrupted_invocations", 0)]))
        self.assertEqual(sorted(phase2.data["plan_totals"]), sorted(pl.STAGES))
        self.assertEqual(list(phase2.data["reports"]), [MODEL])
        self.assertEqual(list(phase2.data["stage_history"]), list(pl.STAGES))
        checks = self.checks_of(sections)
        self.assertIn("not started", json.dumps(checks["population:census_66_66"]["detail"]))
        self.assertEqual(checks["population:census_66_66"]["detail"]["summary"]["blocks"]["pilot"]["not_started_count"], 3)
        self.assertIn("global:population",
                      checks["phase2:reports_reproduce"]["detail"]["models"][MODEL]["differing_checks"])
        self.assertTrue(checks["phase2:reports_present"]["detail"]["run_binding_available"])
        self.assertEqual(checks["population:composite_persisted"]["detail"]["persist"]["note"],
                         "not persisted: preceding checks failed")
        self.assertFalse((self.root / core.COMPOSITE_REL).exists())
        core.json_stable([s.document() for s in sections])

    def test_write_mode_never_persists_a_failed_closure(self):
        """Regression: with FAILing history/population checks the composite
        is not written in --write mode (and composite_persisted FAILs)."""
        calls = []

        def hook(document):
            calls.append(document["composite_sha256"])
            return cc.persist_composite(self.root, document)

        ctx = self.context(write=True, hook=hook)
        sections = study.collect(ctx, models=[MODEL])
        check = self.checks_of(sections)["population:composite_persisted"]
        self.assertEqual(check["status"], core.FAIL)
        self.assertEqual(check["detail"]["note"], "not persisted: preceding checks failed")
        self.assertIn("history:custody_chain", check["detail"]["failing"])
        self.assertEqual(check["detail"]["failing_count"], 7)
        self.assertEqual(calls, [])
        self.assertFalse((self.root / core.COMPOSITE_REL).exists())
        self.assertFalse(sections[1].data["composite"]["persisted"])
        self.assertFalse(sw.lock_path(self.root, PHASE2).exists())

    def test_reports_present_caches_the_reports_without_the_run_binding(self):
        ctx = self.context()
        del ctx.cache["run_bindings"]
        checks = self.checks_of(study.collect(ctx, models=[MODEL]))
        self.assertEqual(checks["phase2:reports_present"]["status"], core.FAIL)
        self.assertFalse(checks["phase2:reports_present"]["detail"]["run_binding_available"])
        self.assertIn("run binding input unavailable", json.dumps(checks["phase2:reports_present"]["detail"]))
        self.assertIsNotNone(ctx.cache.get("phase2_reports"))
        self.assertEqual(checks["phase2:ledger_hygiene"]["status"], core.PASS)
        self.assertEqual(checks["phase2:manifest_invocations_registered"]["status"], core.PASS)

    def test_reports_reproduce_short_circuits_on_a_failed_lineage(self):
        ctx = self.context()

        def drifted():
            raise RecoveryRefused("protected file drifted")

        ctx.lineage.verify = drifted
        timed = []
        ctx.timed = lambda key, function, *a, **kw: timed.append(key) or function(*a, **kw)
        checks = self.checks_of(study.collect(ctx, models=[MODEL]))
        self.assertEqual(checks["history:phase2_lineage_verify"]["status"], core.FAIL)
        self.assertEqual(checks["phase2:reports_reproduce"]["status"], core.FAIL)
        self.assertIn("lineage verification failed", checks["phase2:reports_reproduce"]["detail"])
        self.assertEqual([key for key in timed if key.startswith("verify_model.")], [])
        self.assertIsNone(ctx.cache.get("phase2_verify"))
        self.assertIn("input unavailable", checks["phase2:enhanced_pairs_total"]["detail"])

    def test_census_refuses_a_loaded_provider_module(self):
        ctx = types.SimpleNamespace(root=self.root, cache=OrderedDict(),
                                    timed=lambda key, function, *a, **kw: function(*a, **kw))
        with mock.patch.dict(sys.modules, {"dashscope": types.ModuleType("dashscope")}):
            with self.assertRaisesRegex(ClosureRefused, "dashscope"):
                study._census(ctx, [MODEL])
        self.assertIsNone(ctx.cache.get("census"))
        result, summary = study._census(ctx, [MODEL])
        self.assertEqual(summary["total_repair_loops_done"], "0/6")
        self.assertIs(ctx.cache["census"], result)


# -- real repository (read-only, optional) -------------------------------------------------

@unittest.skipUnless(os.environ.get("STUDY_CLOSURE_REAL") == "1", "set STUDY_CLOSURE_REAL=1 to read the real repository")
class RealRepositoryTest(unittest.TestCase):
    """Read-only checks against the real repository (cheap ones only: the
    definitions chain, the census digest, the stage history)."""

    def test_definitions_census_and_stage_history(self):
        from thesis.recovery_successor_004 import census

        config_path = REPO_ROOT / pl.CONFIG_REL
        facts = study.definitions_bound(REPO_ROOT, config_path)
        lineage = pl.load(REPO_ROOT)
        self.assertEqual(facts["lineage_sha256"], lineage.sha256)
        summary = census.summary(census.census(REPO_ROOT, list(core.MODELS)))
        self.assertEqual(study.census_problems(summary, list(core.MODELS)), [])
        self.assertEqual(study.census_digest(summary), lineage.document["census_digest"])
        problems, detail = study.stage_history(cc.stage_invocation_rows(REPO_ROOT),
                                               study.invocation_fragments(REPO_ROOT), list(core.MODELS))
        self.assertEqual(problems, [])
        self.assertGreaterEqual(detail["interrupted_invocations"], 0)


if __name__ == "__main__":
    unittest.main()
