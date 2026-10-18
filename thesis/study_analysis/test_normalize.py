"""Tests of the study normalizer (normalize.py) on a synthetic repository in
a temp dir: the phase-2 verifier fixture (recovery_successor_005.test_verify
Repo: pilot base + one pilot repair iteration, full_ext base + a
static_feedback and a test_feedback candidate, complete phase-2 ledgers)
extended with an omp base cell, a CONTINUED combined_feedback loop
(iteration 1 requested by full_ext_recovery_001, iteration 2 by
full_ext_recovery_003), the repair state ledgers, wave states and request
rounds of all six loops, generation records and the assembly facts
(cleaning, truncation) the normalizer reads.

    python3 -B -m unittest -v thesis.study_analysis.test_normalize

The real-repository test runs only with STUDY_ANALYSIS_REAL=1 (minutes).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from collections import Counter, OrderedDict

from thesis.study_analysis import core

core.provider_isolation()  # before test_verify loads the phase-2 config (no .env import)

from thesis.evaluation.condition_hashing import canonical_sha256  # noqa: E402
from thesis.recovery_successor_004 import census as cs  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.recovery_successor_005 import targets as pt  # noqa: E402
from thesis.recovery_successor_005 import test_verify as tv  # noqa: E402
from thesis.study_analysis import normalize as nz  # noqa: E402

CONFIG = tv.CONFIG
pl.scrub_provider_environment(CONFIG)
MODEL = tv.MODEL
ORIGIN = pl.ORIGIN
SUCCESSOR = "full_ext_recovery_003"
COMB1 = "full_ext_recovery_001__combined_feedback__iter1"
COMB2 = "full_ext_recovery_003__combined_feedback__iter2"
EXCLUDED = pl.EXCLUDED_HISTORICAL_RUNS[0]
FROZEN_SPECS_REL = "thesis/enhanced_tests/frozen/e3_final_specs.jsonl"
SHAPES_REL = "thesis/enhanced_tests/benchmark_shapes.json"


def sample(benchmark, execution_model):
    kind, name = benchmark.split("/")
    return "%s__%s__%s__%s__sample_0" % (MODEL, kind, name, execution_model)


P_SERIAL, P_OMP = sample(tv.PILOT_BENCH, "serial"), sample(tv.PILOT_BENCH, "omp")
F_SERIAL, F_MPI, F_OMP = (sample(tv.FULL_BENCH, em) for em in ("serial", "mpi", "omp"))
# full_ext target run -> (loop owner, table loop_kind)
OWNERSHIP = OrderedDict([(pl.PARENT, (None, "base")), (tv.STATIC_RUN, (ORIGIN, "native")),
                         (tv.TEST_RUN, (ORIGIN, "native")), (COMB1, (SUCCESSOR, "continued")),
                         (COMB2, (SUCCESSOR, "continued"))])


def loop_plan():
    """(block, variant) -> owner, continued, per-sample status history (index =
    iteration), request rounds {sample: {iteration: rounds}}."""
    def loop(owner, histories, rounds=None, continued=False):
        return OrderedDict([("owner", owner), ("continued", continued), ("histories", histories),
                            ("rounds", rounds or {})])

    return OrderedDict([
        (("pilot", "static_feedback"), loop(pl.PILOT, {P_SERIAL: ["stopped_clean"], P_OMP: ["stopped_clean"]})),
        (("pilot", "test_feedback"), loop(pl.PILOT, {P_SERIAL: ["stopped_tests_pass"],
                                                     P_OMP: ["active", "stopped_tests_pass"]}, {P_OMP: {1: 1}})),
        (("pilot", "combined_feedback"), loop(pl.PILOT, {P_SERIAL: ["stopped_clean"], P_OMP: ["stopped_clean"]})),
        (("full_ext", "static_feedback"), loop(ORIGIN, {F_SERIAL: ["active", "stopped_analysis_incomplete"],
                                                        F_MPI: ["stopped_clean"], F_OMP: ["stopped_clean"]},
                                               {F_SERIAL: {1: 2}})),
        (("full_ext", "test_feedback"), loop(ORIGIN, {F_SERIAL: ["stopped_tests_pass"],
                                                      F_MPI: ["stopped_tests_pass"],
                                                      F_OMP: ["active", "stopped_tests_pass"]}, {F_OMP: {1: 1}})),
        (("full_ext", "combined_feedback"), loop(SUCCESSOR, {F_SERIAL: ["active", "active", "stopped_budget"],
                                                             F_MPI: ["stopped_clean"],
                                                             F_OMP: ["active", "stopped_clean"]},
                                                 {F_SERIAL: {1: 1, 2: 3}, F_OMP: {1: 1}}, continued=True)),
    ])


def cleaning(**overrides):
    block = OrderedDict([
        ("used_fence", False), ("fence_count", 0), ("dropped_leading_lines", 0), ("dropped_trailing_lines", 0),
        ("signature_found_in_output", False), ("signature_matched_patched", False),
        ("dropped_duplicated_prompt_lines", 0), ("kept_pre_signature_lines", 0), ("relocated_includes", []),
        ("braces_balanced", True), ("auto_closed", False), ("signature_suspect", False)])
    block.update(overrides)
    return block


def finding(tool, check_id, blocking, low_confidence=False, message="m", line=3):
    return OrderedDict([("tool", tool), ("check_id", check_id), ("severity", "warning"), ("message", message),
                        ("file", "generated-code.hpp"), ("line", line), ("column", 1), ("blocking", blocking),
                        ("low_confidence", low_confidence), ("path", [])])


def set_findings(entry, findings):
    entry["findings"] = findings
    entry["num_findings"] = len(findings)
    entry["num_blocking"] = sum(1 for f in findings if f["blocking"])
    entry["num_low_confidence"] = sum(1 for f in findings if f["low_confidence"])


class StudyRepo(tv.Repo):
    """The verifier fixture plus everything the normalizer reads."""

    def __init__(self, root):
        super().__init__(root)
        # the fixture's specs are the built-in ones: an empty frozen spec artifact
        # (the normalizer requires the file, the reader falls back on a missing one)
        frozen = self.root / FROZEN_SPECS_REL
        frozen.parent.mkdir(parents=True, exist_ok=True)
        frozen.write_bytes(b"")
        self.runs = OrderedDict()
        self.runs[pl.PILOT] = (None, 0, self.pilot[pl.PILOT])
        self.runs[tv.PILOT_ITER] = ("test_feedback", 1, self.pilot[tv.PILOT_ITER])
        for target in self.table.targets:
            self.runs[target.source_run] = (target.variant, target.iteration, list(target.samples.values()))
        self.add_target(COMB1, "combined_feedback", 1, [(tv.FULL_BENCH, "serial"), (tv.FULL_BENCH, "omp")])
        self.add_target(COMB2, "combined_feedback", 2, [(tv.FULL_BENCH, "serial")])
        self.plan = loop_plan()
        self.write_loops()
        self.write_generations()
        self.rebuild_table()

    # -- overridden builders: the normalizer reads complete records ------------------
    def assembly(self, run, cells):
        if run == pl.PARENT:
            cells = list(cells) + [(tv.FULL_BENCH, "omp")]  # every candidate cell has a base cell
        facts = super().assembly(run, cells)
        path = self.run_path(run, "assembly.jsonl")
        rows = tv.read_jsonl(path)
        for row in rows:
            row["generation_truncated"] = False
            row["cleaning"] = cleaning()
        tv.write_jsonl(path, rows)
        return facts

    def correctness_record(self, run, facts, verdict="pass"):
        record = super().correctness_record(run, facts, verdict)
        record["compile"] = OrderedDict([("ok", verdict != "build_failed"), ("exit_code", 0)])
        return record

    def dynamic_record(self, run, facts):
        from thesis.evaluation import framework
        from thesis.evaluation import run_static_analysis as rsa

        record = super().dynamic_record(run, facts)
        for tool, settings in self.dynamic_settings.items():
            if settings.applies_to(facts["execution_model"]):
                record["tools"][tool] = framework.ToolResult(tool=tool, ran=True, exit_code=0, duration_seconds=1.25,
                                                             analysis_state="COMPLETED").to_dict()
            else:
                record["tools"][tool] = rsa.not_applicable_entry(tool, facts["execution_model"])
        return record

    # -- extensions ------------------------------------------------------------------------
    def target_document(self, run):
        variant, iteration, samples = self.runs[run]
        owner, kind = OWNERSHIP[run]
        relative = pt.run_dir(run, MODEL) + "/assembly.jsonl"
        return OrderedDict([
            ("target_id", "%s/%s" % (MODEL, run)), ("model_id", MODEL), ("block", "full_ext"),
            ("variant", variant), ("iteration", iteration), ("source_run", run), ("loop_owner", owner),
            ("loop_kind", kind), ("assembly", OrderedDict([("path", relative), ("raw_sha256", hashlib.sha256(
                (self.root / relative).read_bytes()).hexdigest())])),
            ("sample_count", len(samples)), ("samples", samples)])

    def add_target(self, run, variant, iteration, cells):
        facts = self.assembly(run, cells)
        self.runs[run] = (variant, iteration, facts)
        self.write_static(run, facts)
        self.write_records(run, facts)
        target = pt.Target(self.target_document(run))
        rows = []
        for sid, fact in target.samples.items():
            for spec in self.specs[fact["benchmark"]]:
                row = self.enhanced_row(run, fact, spec)
                row.update(pt.provenance(target, sid))
                row["phase2_binding"] = self.authority.binding("enhanced", MODEL)
                rows.append(row)
        tv.write_jsonl(self.ledger(run, pt.ENHANCED_FILE), rows)

    def repair_dir(self, run, variant):
        return self.root / pt.INTERMEDIATE_REL / run / MODEL / "repair" / variant

    def write_loop_files(self, run, variant, rows, rounds, predecessor=None, iteration=0):
        directory = self.repair_dir(run, variant)
        directory.mkdir(parents=True, exist_ok=True)
        wave = OrderedDict([("schema_version", "repair_wave.v1"), ("run_id", run), ("model_id", MODEL),
                            ("variant", variant), ("iteration", iteration), ("phase", "done"), ("batch", None),
                            ("repair_condition_sha256", "9" * 64)])
        if predecessor:
            wave["predecessor_run_id"] = predecessor
        (directory / "wave_state.json").write_text(json.dumps(wave), encoding="utf-8")
        tv.write_jsonl(directory / "state.jsonl", rows)
        path = directory / "request_rounds.json"
        if rounds:
            path.write_text(json.dumps(OrderedDict((sid, OrderedDict((str(k), n) for k, n in per.items()))
                                                   for sid, per in rounds.items())), encoding="utf-8")
        elif path.exists():
            path.unlink()

    def state_row(self, run, variant, sample_id, iteration, status):
        return OrderedDict([
            ("schema_version", "repair_state.v2"), ("run_id", run), ("model_id", MODEL), ("variant", variant),
            ("sample_id", sample_id), ("iteration", iteration), ("status", status),
            ("stop_reason", "%s at iteration %d" % (status, iteration)),
            ("test_verdict", "pass" if status == "stopped_tests_pass" else None)])

    def write_loops(self):
        for (block, variant), loop in self.plan.items():
            owner, histories, rounds = loop["owner"], loop["histories"], loop["rounds"]
            rows = [(sid, k, status) for sid, statuses in histories.items() for k, status in enumerate(statuses)]
            top = max(len(statuses) for statuses in histories.values()) - 1
            if loop["continued"]:
                self.write_loop_files(ORIGIN, variant, [self.state_row(ORIGIN, variant, s, k, st)
                                                        for s, k, st in rows if k == 0],
                                      OrderedDict((s, {k: n for k, n in per.items() if k == 1})
                                                  for s, per in rounds.items() if 1 in per))
                self.write_loop_files(owner, variant, [self.state_row(owner, variant, s, k, st)
                                                       for s, k, st in sorted(rows, key=lambda r: r[1]) if k >= 1],
                                      OrderedDict((s, {k: n for k, n in per.items() if k >= 2})
                                                  for s, per in rounds.items() if any(k >= 2 for k in per)),
                                      predecessor=ORIGIN, iteration=top)
            else:
                self.write_loop_files(owner, variant, [self.state_row(owner, variant, s, k, st)
                                                       for s, k, st in sorted(rows, key=lambda r: r[1])],
                                      rounds, iteration=top)

    def generation_row(self, run, variant, iteration, facts):
        base = iteration == 0
        timing = "batch" if run == pl.PILOT else "direct"
        row = OrderedDict([
            ("schema_version", "generation.v3"), ("run_id", run), ("sample_id", facts["sample_id"]),
            ("model", OrderedDict([("id", MODEL), ("provider", "anthropic"), ("model_name", "claude-fable-5")])),
            ("output", OrderedDict([("raw_text", ""), ("cleaned_code", ""), ("finish_reason", "end_turn")])),
            ("api_response", OrderedDict([("usage_normalized", OrderedDict([
                ("input_tokens", 100 + iteration), ("output_tokens", 50 + iteration),
                ("reasoning_tokens", None if run == tv.TEST_RUN else 7)]))])),
            # a batch row carrying a span: never a latency
            ("status", OrderedDict([("success", True), ("truncated", False),
                                    ("duration_seconds", 999.0 if timing == "batch" else 12.5),
                                    ("timing_mode", timing)]))])
        if not base:
            row["repair"] = OrderedDict([("variant", variant), ("iteration", iteration), ("strategy", variant),
                                         ("built_from_iteration", iteration - 1), ("request_chars", 1000 + iteration)])
        return row

    def generations_path(self, run):
        return self.root / pt.RAW_REL / run / MODEL / "generations.jsonl"

    def write_generations(self):
        for run, (variant, iteration, samples) in self.runs.items():
            tv.write_jsonl(self.generations_path(run), [self.generation_row(run, variant, iteration, f)
                                                        for f in samples])

    def census(self):
        return cs.census(self.root, [MODEL])

    def rebuild_table(self, census_digest=None):
        documents = [self.target_document(run) for run in OWNERSHIP]
        document = OrderedDict([
            ("schema_version", pt.SCHEMA), ("run_id", pl.SUCCESSOR), ("model_ids", list(pl.MODELS)),
            ("excluded_historical_runs", list(pl.EXCLUDED_HISTORICAL_RUNS)),
            ("census_digest", census_digest or canonical_sha256(cs.summary(self.census()))),
            ("census_summary", OrderedDict()), ("target_count", len(documents)),
            ("sample_totals", OrderedDict()), ("targets", documents)])
        document["table_sha256"] = canonical_sha256(document)
        self.table = pt.TargetTable(self.root, document)
        return self.table


def aid(block, run, sample_id):
    return core.artifact_id(block, MODEL, run, sample_id)


class NormalizeTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="study_normalize_")
        self.repo = StudyRepo(self._tmp)
        self.root = self.repo.root

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def build(self, census_digest=None, **kwargs):
        self.repo.rebuild_table(census_digest)
        return nz.build_dataset(self.root, CONFIG, self.repo.table, models=[MODEL], **kwargs)

    def refuses(self, pattern):
        with self.assertRaisesRegex(core.AnalysisRefused, pattern):
            self.build()

    def edit_static(self, run, sample_id, function, phase2_tool=None):
        def edit(rows):
            for row in rows:
                if row["sample_id"] == sample_id:
                    function(row["entry"] if phase2_tool else row)
            return rows

        path = self.repo.ledger(run, "static.%s.jsonl" % phase2_tool) if phase2_tool else \
            self.repo.run_path(run, pt.STATIC_FILE)
        tv.edit_jsonl(path, edit)

    def rewrite_loops(self, function):
        function(self.repo.plan)
        self.repo.write_loops()


class DatasetTest(NormalizeTestBase):
    def test_happy_path_counts_owners_and_determinism(self):
        dataset = self.build(lineage_sha256="e" * 64)
        self.assertEqual(dataset.counts(), OrderedDict([
            ("base_cells", 5), ("artifacts", 11), ("tool_entries", 121), ("findings", 0), ("enhanced_pairs", 220),
            ("trajectories", 15), ("generations", 11)]))
        artifacts = dataset.by("artifacts", "artifact_id")
        self.assertEqual(Counter((r["block"], r["iteration"]) for r in artifacts.values()),
                         Counter({("pilot", 0): 2, ("pilot", 1): 1, ("full_ext", 0): 3, ("full_ext", 1): 4,
                                  ("full_ext", 2): 1}))
        self.assertEqual([r["block"] for r in dataset.rows("base_cells")], ["pilot"] * 2 + ["full_ext"] * 3)
        for row in dataset.rows("base_cells"):
            self.assertEqual(row["base_run"], core.BLOCK_BASE_RUN[row["block"]])
            self.assertFalse(row["bl01"])
        pilot_base = artifacts[aid("pilot", pl.PILOT, P_SERIAL)]
        self.assertEqual((pilot_base["variant"], pilot_base["loop_owner"], pilot_base["static_owner"],
                          pilot_base["correctness_owner"], pilot_base["dynamic_owner"], pilot_base["enhanced_owner"]),
                         ("", "", pl.PILOT, pl.PILOT, pl.PILOT, pl.PILOT))
        self.assertEqual(artifacts[aid("pilot", tv.PILOT_ITER, P_OMP)]["loop_owner"], pl.PILOT)
        base = artifacts[aid("full_ext", pl.PARENT, F_SERIAL)]
        self.assertEqual((base["loop_owner"], base["correctness_owner"], base["enhanced_owner"]),
                         ("", pl.PARENT, pl.SUCCESSOR))
        static = artifacts[aid("full_ext", tv.STATIC_RUN, F_SERIAL)]
        self.assertEqual((static["static_owner"], static["correctness_owner"], static["dynamic_owner"],
                          static["loop_owner"]), (tv.STATIC_RUN, pl.SUCCESSOR, pl.SUCCESSOR, ORIGIN))
        test = artifacts[aid("full_ext", tv.TEST_RUN, F_OMP)]
        self.assertEqual(test["static_supplemented_by"], OrderedDict([("parcoach", pl.SUCCESSOR),
                                                                      ("llov", pl.SUCCESSOR)]))
        self.assertEqual(artifacts[aid("full_ext", COMB2, F_SERIAL)]["loop_owner"], SUCCESSOR)
        for row in artifacts.values():
            self.assertEqual(row["cell_id"], core.cell_id(row["block"], MODEL, row["sample_id"]))
            self.assertEqual((row["static_three_state"], row["dynamic_three_state"]),
                             ("CLEAN_COMPLETE", "CLEAN_COMPLETE"))
            self.assertEqual((row["correctness_verdict"], row["build_ok"], row["generation_success"],
                              row["assembled"], row["clean_any"], row["compile_error"]),
                             ("pass", True, True, True, False, False))
            self.assertEqual((row["enh_pairs"], row["enh_valid"], row["enh_pass"], row["enh_all_pass"]),
                             (20, 20, 20, 1))
            self.assertEqual(list(row), list(core.SCHEMAS["artifacts"]))
        for name, rows in dataset.tables.items():
            for row in rows:
                self.assertEqual(list(row), list(core.SCHEMAS[name]), name)
            core.table_csv_bytes(name, rows)
        entries = dataset.rows("tool_entries")
        self.assertEqual(Counter(r["state"] for r in entries)["ABSENT_INAPPLICABLE"], 6)
        absent = [r for r in entries if r["state"] == "ABSENT_INAPPLICABLE"]
        self.assertTrue(all(r["artifact_id"].startswith("pilot|") and not r["applicable"] and not r["ran"]
                            and r["duration_seconds"] is None and r["owner"] == pl.PILOT for r in absent))
        self.assertEqual(sorted(set(r["tool"] for r in absent)), ["infer", "llov", "parcoach"])
        provenance = dataset.provenance
        self.assertEqual(provenance["targets_sha256"], self.repo.table.sha256)
        self.assertEqual(provenance["lineage_sha256"], "e" * 64)
        self.assertEqual(provenance["census_digest"], canonical_sha256(cs.summary(self.repo.census())))
        self.assertIn("thesis.recovery_successor_005.composite", provenance["readers"])
        self.assertEqual(provenance["gated_groups"], 0)
        # deterministic: a second build is byte-identical
        again = self.build(lineage_sha256="e" * 64)
        for name in core.SCHEMAS:
            self.assertEqual(core.table_csv_bytes(name, dataset.rows(name)), core.table_csv_bytes(name, again.rows(name)))
        self.assertEqual(json.dumps(provenance), json.dumps(again.provenance))
        self.assertEqual(list(nz.iter_study_targets(self.root, self.repo.table, [MODEL]))[0][1].source_run, pl.PILOT)

    def test_cleaning_flags(self):
        def edit(rows):
            rows[0]["cleaning"] = cleaning(used_fence=True, dropped_leading_lines=2,
                                           relocated_includes=["#include <cmath>"], braces_balanced=False)
            rows[1]["cleaning"] = cleaning(used_fence=True)
            rows[2]["cleaning"] = cleaning(auto_closed=True, dropped_duplicated_prompt_lines=1)
            rows[2]["generation_truncated"] = True
            return rows

        tv.edit_jsonl(self.repo.run_path(pl.PARENT, "assembly.jsonl"), edit)
        artifacts = self.build().by("artifacts", "artifact_id")
        first, second, third = (artifacts[aid("full_ext", pl.PARENT, s)] for s in (F_SERIAL, F_MPI, F_OMP))
        self.assertEqual([first[c] for c in ("clean_used_fence", "clean_dropped_leading_lines",
                                             "clean_relocated_includes", "clean_braces_unbalanced",
                                             "clean_auto_closed", "clean_any", "clean_any_including_fence")],
                         [True, True, True, True, False, True, True])
        self.assertEqual((second["clean_any"], second["clean_any_including_fence"]), (False, True))
        self.assertEqual((third["clean_auto_closed"], third["clean_dropped_duplicated_prompt_lines"],
                          third["clean_any"], third["generation_truncated"]), (True, True, True, True))

        def drop(rows):
            del rows[0]["cleaning"]
            return rows

        tv.edit_jsonl(self.repo.run_path(pl.PARENT, "assembly.jsonl"), drop)
        self.refuses("no cleaning block")

    def test_non_assembled_answer_refuses(self):
        # the pilot reader drops non-assembled rows silently; the normalizer must not
        def unassembled(rows):
            row = json.loads(json.dumps(rows[0]))
            row["sample_id"] = P_SERIAL
            row["assembled"] = False
            return rows + [row]

        tv.edit_jsonl(self.repo.run_path(tv.PILOT_ITER, "assembly.jsonl"), unassembled)
        self.refuses("non-assembled answer")


class TrajectoryTest(NormalizeTestBase):
    def trajectories(self):
        return self.build().by("trajectories", "trajectory_id")

    def test_trajectory_overlay_of_a_continued_loop(self):
        rows = self.trajectories()
        cell = core.cell_id("full_ext", MODEL, F_SERIAL)
        row = rows[core.trajectory_id(cell, "combined_feedback")]
        self.assertEqual((row["loop_owner"], row["loop_kind"], row["final_iteration"], row["terminal_status"]),
                         (SUCCESSOR, "continued", 2, "stopped_budget"))
        # iteration 0 from recovery_001's ledger, iterations 1/2 from the successor's
        self.assertEqual((row["status_iter0"], row["status_iter1"], row["status_iter2"]),
                         ("active", "active", "stopped_budget"))
        self.assertEqual((row["artifact_iter0"], row["artifact_iter1"], row["artifact_iter2"], row["final_artifact"]),
                         (aid("full_ext", pl.PARENT, F_SERIAL), aid("full_ext", COMB1, F_SERIAL),
                          aid("full_ext", COMB2, F_SERIAL), aid("full_ext", COMB2, F_SERIAL)))
        self.assertEqual(row["request_rounds"], 4)  # recovery_001 iteration 1 (1) + successor iteration 2 (3)
        self.assertEqual(row["stop_reason"], "stopped_budget at iteration 2")
        omp = rows[core.trajectory_id(core.cell_id("full_ext", MODEL, F_OMP), "combined_feedback")]
        self.assertEqual((omp["final_iteration"], omp["status_iter1"], omp["status_iter2"], omp["artifact_iter2"],
                          omp["final_artifact"], omp["request_rounds"]),
                         (1, "stopped_clean", "", "", aid("full_ext", COMB1, F_OMP), 1))
        mpi = rows[core.trajectory_id(core.cell_id("full_ext", MODEL, F_MPI), "combined_feedback")]
        self.assertEqual((mpi["final_iteration"], mpi["final_artifact"], mpi["request_rounds"], mpi["status_iter1"]),
                         (0, aid("full_ext", pl.PARENT, F_MPI), 0, ""))
        native = rows[core.trajectory_id(cell, "static_feedback")]
        self.assertEqual((native["loop_owner"], native["loop_kind"], native["final_artifact"],
                          native["request_rounds"]), (ORIGIN, "native", aid("full_ext", tv.STATIC_RUN, F_SERIAL), 2))
        test = rows[core.trajectory_id(core.cell_id("pilot", MODEL, P_OMP), "test_feedback")]
        self.assertEqual((test["loop_owner"], test["loop_kind"], test["test_verdict_final"], test["final_artifact"]),
                         (pl.PILOT, "native", "pass", aid("pilot", tv.PILOT_ITER, P_OMP)))
        self.assertEqual(Counter(r["terminal_status"] for r in rows.values() if r["block"] == "full_ext"),
                         Counter(cs.summary(self.repo.census())["blocks"]["full_ext"]["sample_states"]))

    def test_missing_artifact_within_final_refuses(self):
        def edit(plan):
            loop = plan[("pilot", "static_feedback")]
            loop["histories"][P_SERIAL] = ["active", "stopped_budget"]
            loop["rounds"] = {P_SERIAL: {1: 1}}

        self.rewrite_loops(edit)
        self.refuses("missing iteration-1 artifact")

    def test_candidate_beyond_final_refuses(self):
        def edit(plan):
            loop = plan[("full_ext", "test_feedback")]
            loop["histories"][F_OMP] = ["stopped_tests_pass"]
            loop["rounds"] = {}

        self.rewrite_loops(edit)
        self.refuses("beyond the final iteration 0")

    def test_non_active_row_before_final_refuses(self):
        self.rewrite_loops(lambda plan: plan[("pilot", "test_feedback")]["histories"].__setitem__(
            P_OMP, ["stopped_clean", "stopped_tests_pass"]))
        self.refuses("non-active row before its final row")

    def test_iteration_gap_refuses(self):
        path = self.repo.repair_dir(SUCCESSOR, "combined_feedback") / "state.jsonl"
        tv.edit_jsonl(path, lambda rows: [r for r in rows if not (r["sample_id"] == F_SERIAL and r["iteration"] == 1)])
        self.refuses(r"iteration history \[0, 2\]")

    def test_request_rounds_must_cover_exactly_the_requested_iterations(self):
        self.rewrite_loops(lambda plan: plan[("full_ext", "combined_feedback")]["rounds"].__setitem__(
            F_SERIAL, {1: 1}))
        self.refuses("request rounds recorded for iterations")

    def test_census_bindings(self):
        with self.assertRaisesRegex(core.AnalysisRefused, "frozen on another census"):
            self.build(census_digest="0" * 64)
        wave = self.repo.repair_dir(pl.PILOT, "combined_feedback") / "wave_state.json"
        document = json.loads(wave.read_text(encoding="utf-8"))
        document["phase"] = "repairing"
        wave.write_text(json.dumps(document), encoding="utf-8")
        self.refuses("not terminal")


class EvidenceTest(NormalizeTestBase):
    def test_absent_entry_applicable_refuses_inapplicable_is_absent_inapplicable(self):
        entries = [r for r in self.build().rows("tool_entries")
                   if r["artifact_id"] == aid("pilot", pl.PILOT, P_SERIAL)]
        self.assertEqual([(r["stage"], r["tool"], r["state"]) for r in entries if not r["applicable"]],
                         [("static", "parcoach", "ABSENT_INAPPLICABLE"), ("static", "llov", "ABSENT_INAPPLICABLE"),
                          ("dynamic", "tsan", "NOT_APPLICABLE"), ("dynamic", "must", "NOT_APPLICABLE")])
        self.edit_static(pl.PILOT, P_SERIAL, lambda row: row["tools"].pop("infer"))
        self.refuses("no entry for the applicable tool")

    def test_recorded_scope_contradiction_refuses(self):
        def contradict(row):
            row["tools"]["llov"]["analysis_state"] = "COMPLETED"  # llov does not apply to serial

        self.edit_static(pl.PARENT, F_SERIAL, contradict)
        self.refuses("contradicts the frozen scope")

    def test_finding_kinds_families_and_counts(self):
        from thesis.evaluation.finding_classes import classify_finding

        def inject(row):
            set_findings(row["tools"]["gcc_analyzer"], [
                finding("gcc_analyzer", "-Wanalyzer-null-dereference", True),
                finding("gcc_analyzer", "-Wanalyzer-use-of-uninitialized-value", True, low_confidence=True),
                finding("gcc_analyzer", "-Wanalyzer-malloc-leak", False, line=None)])
            set_findings(row["tools"]["compiler"], [finding("compiler", "error", True, message="expected ';'")])

        self.edit_static(pl.PARENT, F_SERIAL, inject)
        dataset = self.build()
        artifact_id = aid("full_ext", pl.PARENT, F_SERIAL)
        findings = [r for r in dataset.rows("findings") if r["artifact_id"] == artifact_id]
        self.assertEqual([(r["tool"], r["kind"]) for r in findings],
                         [("compiler", "reported_blocking"), ("gcc_analyzer", "reported_blocking"),
                          ("gcc_analyzer", "low_confidence"), ("gcc_analyzer", "non_blocking")])
        for row in findings:
            self.assertEqual(row["family"], classify_finding(row["tool"], row["check_id"],
                                                             "expected ';'" if row["tool"] == "compiler" else "m"))
        self.assertEqual([r["line"] for r in findings], [3, 3, 3, None])
        gcc = [r for r in dataset.rows("tool_entries") if r["artifact_id"] == artifact_id
               and r["tool"] == "gcc_analyzer"][0]
        self.assertEqual((gcc["num_findings"], gcc["num_reported_blocking"], gcc["num_low_confidence"],
                          gcc["num_non_blocking"], gcc["owner"]), (3, 1, 1, 1, pl.PARENT))
        artifact = dataset.by("artifacts", "artifact_id")[artifact_id]
        self.assertEqual((artifact["compile_error"], artifact["low_confidence_any"], artifact["static_three_state"]),
                         (True, True, "DIRTY"))

    def test_three_state_verdicts(self):
        self.edit_static(pl.PARENT, F_MPI, lambda row: row["tools"]["gcc_analyzer"].update(analysis_state="PARTIAL"))
        self.edit_static(pl.PARENT, F_OMP, lambda row: set_findings(row["tools"]["compiler"], [
            finding("compiler", "error", True)]))
        self.edit_static(tv.STATIC_RUN, F_SERIAL, lambda row: set_findings(row["tools"]["clang_tidy"], [
            finding("clang_tidy", "clang-analyzer-optin.mpi.MPI-Checker", True, low_confidence=True)]))

        def partial_dirty(row):
            row["tools"]["infer"]["analysis_state"] = "TIMEOUT"
            set_findings(row["tools"]["infer"], [finding("infer", "NULL_DEREFERENCE", True)])

        self.edit_static(COMB2, F_SERIAL, partial_dirty)

        def dynamic(rows):
            for row in rows:
                if row["sample_id"] == F_OMP:
                    set_findings(row["tools"]["tsan"], [finding("tsan", "tsan-data-race", True)])
                if row["sample_id"] == F_MPI:
                    row["tools"]["must"]["analysis_state"] = "TIMEOUT"
            return rows

        tv.edit_jsonl(self.repo.run_path(pl.PARENT, pt.DYNAMIC_FILE), dynamic)
        dataset = self.build()
        artifacts = dataset.by("artifacts", "artifact_id")
        mpi, omp = artifacts[aid("full_ext", pl.PARENT, F_MPI)], artifacts[aid("full_ext", pl.PARENT, F_OMP)]
        # PARTIAL without a finding is an analysis gap, never clean
        self.assertEqual((mpi["static_three_state"], mpi["static_analysis_complete"]),
                         ("NO_FINDING_INCOMPLETE", False))
        self.assertEqual((mpi["dynamic_three_state"], mpi["dynamic_analysis_complete"]),
                         ("NO_FINDING_INCOMPLETE", False))
        # the compiler is a build precondition, not an analysis tool
        self.assertEqual((omp["compile_error"], omp["static_three_state"], omp["dynamic_three_state"]),
                         (True, "CLEAN_COMPLETE", "DIRTY"))
        low = artifacts[aid("full_ext", tv.STATIC_RUN, F_SERIAL)]
        self.assertEqual((low["static_three_state"], low["low_confidence_any"]), ("CLEAN_COMPLETE", True))
        # a reported blocking finding counts whatever the tool state (frozen rule) - and is disclosed
        self.assertEqual(artifacts[aid("full_ext", COMB2, F_SERIAL)]["static_three_state"], "DIRTY")
        self.assertEqual(dataset.provenance["dirty_only_from_gap_state_entries"], OrderedDict([
            ("states", ["TIMEOUT", "TOOL_ERROR", "NOT_ANALYZED"]),
            ("artifacts", OrderedDict([("static/full_ext/REPAIR_CANDIDATES", 1)])),
            ("entries", OrderedDict([("static/full_ext/REPAIR_CANDIDATES/infer/TIMEOUT", 1)]))]))

    def test_subsumed_not_analyzed_entry_with_blocking_findings(self):
        """The real case: clang-tidy prints bugprone diagnostics, then its front end
        rejects the TU the compiler also rejected (effective state NOT_ANALYZED)."""
        def rejected(row, gcc_finding=False):
            compiler = row["tools"]["compiler"]
            compiler["exit_code"] = 1
            set_findings(compiler, [finding("compiler", "error", True, message="expected ';'")])
            tidy = row["tools"]["clang_tidy"]
            tidy.update(analysis_state="TOOL_ERROR", analysis_gap_reason="clang-diagnostic-error",
                        analysis_details=OrderedDict([("tu_rejected", True)]))
            set_findings(tidy, [finding("clang_tidy", "bugprone-integer-division", True)])
            if gcc_finding:  # a defect of a COMPLETED analysis: DIRTY under either reading
                set_findings(row["tools"]["gcc_analyzer"], [finding("gcc_analyzer", "-Wanalyzer-null-dereference",
                                                                    True)])

        self.edit_static(pl.PARENT, F_SERIAL, rejected)
        self.edit_static(tv.STATIC_RUN, F_SERIAL, lambda row: rejected(row, gcc_finding=True))
        dataset = self.build()
        artifacts = dataset.by("artifacts", "artifact_id")
        base_id, candidate_id = aid("full_ext", pl.PARENT, F_SERIAL), aid("full_ext", tv.STATIC_RUN, F_SERIAL)
        entries = [r for r in dataset.rows("tool_entries") if r["artifact_id"] == base_id and r["stage"] == "static"]
        tidy = [r for r in entries if r["tool"] == "clang_tidy"][0]
        self.assertEqual((tidy["state"], tidy["applicable"], tidy["num_reported_blocking"]), ("NOT_ANALYZED", True, 1))
        # frozen literal rule: DIRTY; framework.tool_verdict reading: an analysis gap
        self.assertEqual((artifacts[base_id]["static_three_state"], artifacts[base_id]["compile_error"],
                          artifacts[base_id]["static_analysis_complete"]), ("DIRTY", True, False))
        self.assertEqual(nz.three_state(entries, core.STATIC_ANALYSIS_TOOLS), "DIRTY")
        self.assertEqual(nz.VERDICT_STATES, ("COMPLETED", "PARTIAL"))
        self.assertEqual(nz.three_state(entries, core.STATIC_ANALYSIS_TOOLS, nz.VERDICT_STATES),
                         "NO_FINDING_INCOMPLETE")
        self.assertEqual(artifacts[candidate_id]["static_three_state"], "DIRTY")
        candidate = [r for r in dataset.rows("tool_entries") if r["artifact_id"] == candidate_id]
        self.assertEqual(nz.three_state(candidate, core.STATIC_ANALYSIS_TOOLS, nz.VERDICT_STATES), "DIRTY")
        self.assertEqual(nz.gap_state_dirty_entries(candidate, core.STATIC_ANALYSIS_TOOLS), [])
        # only the base artifact is DIRTY through the gap-state entry alone
        self.assertEqual(dataset.provenance["dirty_only_from_gap_state_entries"]["artifacts"],
                         OrderedDict([("static/full_ext/BASE", 1)]))
        self.assertEqual(dataset.provenance["dirty_only_from_gap_state_entries"]["entries"],
                         OrderedDict([("static/full_ext/BASE/clang_tidy/NOT_ANALYZED", 1)]))
        self.assertEqual(dataset.provenance["effective_state_overrides"],
                         OrderedDict([("static/clang_tidy/TOOL_ERROR->NOT_ANALYZED", 2)]))

    def test_stage_without_applicable_tool_refuses(self):
        rows = [r for r in self.build().rows("tool_entries") if r["artifact_id"] == aid("pilot", pl.PILOT, P_SERIAL)]
        dynamic = [r for r in rows if r["stage"] == "dynamic"]
        self.assertEqual(nz.three_state(dynamic, core.DYNAMIC_TOOLS), "CLEAN_COMPLETE")
        for function in (nz.three_state, nz.analysis_complete, nz.gap_state_dirty_entries):
            with self.assertRaisesRegex(core.AnalysisRefused, "no applicable tool"):
                function([], core.STATIC_ANALYSIS_TOOLS)
            with self.assertRaisesRegex(core.AnalysisRefused, "no applicable tool"):
                function([OrderedDict(r, applicable=False) for r in dynamic], core.DYNAMIC_TOOLS)

    def test_static_record_source_binding(self):
        self.edit_static(pl.PARENT, F_MPI, lambda row: row.update(sample_source_sha256="0" * 64))
        self.refuses("bound to another source")
        self.edit_static(pl.PARENT, F_MPI, lambda row: row.pop("sample_source_sha256"))
        self.refuses("carries no sample_source_sha256")

    def test_non_object_rows_refuse_as_analysis_refusals(self):
        generations = self.repo.generations_path(tv.STATIC_RUN)
        rows = tv.read_jsonl(generations)
        tv.write_jsonl(generations, rows + [["not", "an", "object"]])
        self.refuses(r"generations.jsonl row 2 is not an object")
        # a wrong JSON type deeper in a row: the AttributeError becomes a refusal naming the target
        tv.write_jsonl(generations, [OrderedDict(r, model="claude") for r in rows])
        self.refuses(r"target %s/%s: AttributeError" % (MODEL, tv.STATIC_RUN))
        # an own state-ledger read (no census involved)
        relative = "%s/run/m/repair/static_feedback/state.jsonl" % pt.INTERMEDIATE_REL
        (self.root / relative).parent.mkdir(parents=True)
        (self.root / relative).write_text('["not", "an", "object"]\n', encoding="utf-8")
        with self.assertRaisesRegex(core.AnalysisRefused, "state.jsonl row 1 is not an object"):
            nz._state_rows(nz.FilesRead(self.root), "run", "m", "static_feedback")

    def test_correctness_record_vocabulary_and_presence(self):
        tv.edit_jsonl(self.repo.run_path(pl.PARENT, pt.CORRECTNESS_FILE),
                      lambda rows: [OrderedDict(r, verdict="flaky") if r["sample_id"] == F_MPI else r for r in rows])
        self.refuses("correctness verdict 'flaky'")
        tv.write_jsonl(self.repo.ledger(tv.STATIC_RUN, pt.CORRECTNESS_FILE), [])
        tv.edit_jsonl(self.repo.run_path(pl.PARENT, pt.CORRECTNESS_FILE),
                      lambda rows: [OrderedDict(r, verdict="pass") for r in rows])
        self.refuses("no correctness record")

    def test_build_failed_verdict_and_build_ok(self):
        tv.edit_jsonl(self.repo.run_path(tv.TEST_RUN, pt.CORRECTNESS_FILE), lambda rows: [
            self.repo.correctness_record(tv.TEST_RUN, OrderedDict(r), "build_failed") for r in rows])
        artifact = self.build().by("artifacts", "artifact_id")[aid("full_ext", tv.TEST_RUN, F_OMP)]
        self.assertEqual((artifact["correctness_verdict"], artifact["build_ok"]), ("build_failed", False))

    def test_excluded_run_on_disk_is_ignored(self):
        baseline = self.build()
        # the aborted repair inside the base run, complete with records and a repair ledger
        facts = self.repo.assembly(EXCLUDED, [(tv.FULL_BENCH, "serial")])
        self.repo.write_static(EXCLUDED, facts)
        self.repo.write_records(EXCLUDED, facts)
        tv.write_jsonl(self.repo.generations_path(EXCLUDED), [self.repo.generation_row(
            EXCLUDED, "static_feedback", 1, facts[0])])
        self.repo.write_loop_files(pl.PARENT, "static_feedback", [self.repo.state_row(
            pl.PARENT, "static_feedback", F_SERIAL, 0, "active")], {F_SERIAL: {1: 1}})
        dataset = self.build()
        self.assertEqual(dataset.counts(), baseline.counts())
        self.assertFalse([p for p in dataset.provenance["files_read"] if EXCLUDED in p or "/full_ext_001/" in p
                          and "/repair/" in p])
        self.assertFalse([r for r in dataset.rows("artifacts") if r["source_run"] in core.EXCLUDED_RUNS])
        self.assertEqual(core.table_csv_bytes("trajectories", dataset.rows("trajectories")),
                         core.table_csv_bytes("trajectories", baseline.rows("trajectories")))


class EnhancedTest(NormalizeTestBase):
    def gate(self, statuses):
        """statuses: run -> status of the first spec of every serial full_ext sample."""
        from thesis.enhanced_tests.specs import spec_key
        from thesis.recovery_successor_005 import ledger as pg

        first = pg.key_text(spec_key(self.repo.specs[tv.FULL_BENCH][0]))
        for run, status in statuses.items():
            def edit(rows, status=status):
                return [OrderedDict(r, status=status) if r["sample_id"] == F_SERIAL
                        and pg.key_text(spec_key(r["spec"])) == first else r for r in rows]

            tv.edit_jsonl(self.repo.ledger(run, pt.ENHANCED_FILE), edit)

    def test_mixed_gate_within_a_group_refuses(self):
        self.gate({pl.PARENT: "baseline_incompatible"})
        self.refuses("mix gated and valid pairs")

    def test_uniform_gate_is_counted_not_refused(self):
        self.gate(OrderedDict((run, "numerically_unstable") for run in (pl.PARENT, tv.STATIC_RUN, COMB1, COMB2)))
        dataset = self.build()
        artifact = dataset.by("artifacts", "artifact_id")[aid("full_ext", tv.STATIC_RUN, F_SERIAL)]
        self.assertEqual((artifact["enh_pairs"], artifact["enh_valid"], artifact["enh_gated"], artifact["enh_pass"],
                          artifact["enh_all_pass"]), (20, 19, 1, 19, 1))
        self.assertEqual(dataset.provenance["gated_groups"], 1)
        self.assertEqual(sum(1 for p in dataset.rows("enhanced_pairs") if p["gated"]), 4)

    def test_status_counts_and_all_pass(self):
        def edit(rows):
            for i, row in enumerate(r for r in rows if r["sample_id"] == F_MPI):
                row["status"] = ("fail", "crash", "timeout", "build_failed", "runtime_error")[i] if i < 5 else "pass"
            return rows

        tv.edit_jsonl(self.repo.ledger(pl.PARENT, pt.ENHANCED_FILE), edit)
        dataset = self.build()
        artifact = dataset.by("artifacts", "artifact_id")[aid("full_ext", pl.PARENT, F_MPI)]
        self.assertEqual([artifact[c] for c in ("enh_valid", "enh_pass", "enh_fail", "enh_crash", "enh_timeout",
                                                "enh_build_failed", "enh_runtime_error", "enh_all_pass")],
                         [20, 15, 1, 1, 1, 1, 1, 0])
        pair = [p for p in dataset.rows("enhanced_pairs") if p["artifact_id"] == artifact["artifact_id"]][0]
        spec = self.repo.specs[tv.FULL_BENCH][0]
        self.assertEqual((pair["size"], pair["pattern"], pair["spec_source"], pair["gated"]),
                         (spec["size"], spec["pattern"], spec["source"], False))
        tv.edit_jsonl(self.repo.ledger(pl.PARENT, pt.ENHANCED_FILE),
                      lambda rows: [OrderedDict(r, status="flaky") for r in rows])
        self.refuses("enhanced status 'flaky'")

    def test_duplicate_enhanced_pair_refuses(self):
        tv.edit_jsonl(self.repo.ledger(tv.TEST_RUN, pt.ENHANCED_FILE), lambda rows: rows + [rows[3]])
        self.refuses("duplicate enhanced")

    def test_pilot_duplicate_and_missing_pairs_refuse(self):
        path = self.repo.run_path(tv.PILOT_ITER, pt.ENHANCED_FILE)
        rows = tv.read_jsonl(path)
        tv.write_jsonl(path, rows + [rows[0]])
        self.refuses("duplicate enhanced")
        tv.write_jsonl(path, rows[1:])
        self.refuses("1 missing")


class GenerationTest(NormalizeTestBase):
    def test_generation_columns_and_direct_duration_only(self):
        dataset = self.build()
        rows = dataset.by("generations", "artifact_id")
        pilot = rows[aid("pilot", pl.PILOT, P_SERIAL)]
        self.assertEqual((pilot["kind"], pilot["timing_mode"], pilot["duration_seconds"], pilot["request_chars"]),
                         ("base", "batch", None, None))
        base = rows[aid("full_ext", pl.PARENT, F_SERIAL)]
        self.assertEqual((base["timing_mode"], base["duration_seconds"]), ("direct", 12.5))
        repair = rows[aid("full_ext", COMB2, F_SERIAL)]
        self.assertEqual((repair["kind"], repair["provider"], repair["success"], repair["request_chars"],
                          repair["input_tokens"], repair["output_tokens"], repair["reasoning_tokens"],
                          repair["finish_reason"]), ("repair", "anthropic", True, 1002, 102, 52, 7, "end_turn"))
        self.assertIsNone(rows[aid("full_ext", tv.TEST_RUN, F_OMP)]["reasoning_tokens"])  # None stays None
        self.assertEqual(Counter(r["kind"] for r in rows.values()), Counter({"base": 5, "repair": 6}))

    def test_generation_rows_are_exact(self):
        path = self.repo.generations_path(tv.STATIC_RUN)
        rows = tv.read_jsonl(path)
        tv.write_jsonl(path, [])
        self.refuses("no generation record")
        stray = json.loads(json.dumps(rows[0]))
        stray["sample_id"] = F_MPI
        tv.write_jsonl(path, rows + [stray])
        self.refuses("generation rows without an artifact")
        tv.write_jsonl(path, rows + rows)
        self.refuses("foreign or duplicate generation row")
        wrong = json.loads(json.dumps(rows[0]))
        wrong["repair"]["iteration"] = 2
        tv.write_jsonl(path, [wrong])
        self.refuses("another iteration/variant")

    def test_token_fields_present_and_only_reasoning_nullable(self):
        path = self.repo.generations_path(tv.STATIC_RUN)
        rows = tv.read_jsonl(path)

        def usage(**changes):
            row = json.loads(json.dumps(rows[0]), object_pairs_hook=OrderedDict)
            block = row["api_response"]["usage_normalized"]
            for key, value in changes.items():
                if value is KeyError:
                    del block[key]
                else:
                    block[key] = value
            tv.write_jsonl(path, [row])

        usage(output_tokens=KeyError)  # schema drift is not "provider reports no field"
        self.refuses("usage_normalized lacks output_tokens")
        usage(reasoning_tokens=KeyError)
        self.refuses("usage_normalized lacks reasoning_tokens")
        usage(input_tokens=None)
        self.refuses(r"usage_normalized.input_tokens is null")
        usage(output_tokens=None)
        self.refuses(r"usage_normalized.output_tokens is null")
        usage(reasoning_tokens=None)
        generation = self.build().by("generations", "artifact_id")[aid("full_ext", tv.STATIC_RUN, F_SERIAL)]
        self.assertEqual((generation["input_tokens"], generation["output_tokens"], generation["reasoning_tokens"]),
                         (101, 51, None))


class FilesReadTest(NormalizeTestBase):
    def test_files_read_are_hashed_once_and_complete(self):
        dataset = self.build()
        read = dataset.provenance["files_read"]
        self.assertEqual(list(read), sorted(read))
        for relative, digest in read.items():
            self.assertEqual(hashlib.sha256((self.root / relative).read_bytes()).hexdigest(), digest, relative)
        expected = [pt.run_dir(run, MODEL) + "/assembly.jsonl" for run in self.repo.runs]
        expected += [pt.run_dir(run, MODEL) + "/" + name for run in self.repo.runs
                     for name in (pt.STATIC_FILE, pt.CORRECTNESS_FILE, pt.DYNAMIC_FILE)
                     if (self.root / pt.run_dir(run, MODEL) / name).is_file()]
        expected += [pt.run_dir(run, MODEL) + "/" + pt.ENHANCED_FILE for run in (pl.PILOT, tv.PILOT_ITER)]
        expected += [pt.ledger_relative(MODEL, run, pt.ENHANCED_FILE) for run in OWNERSHIP]
        expected += [pt.ledger_relative(MODEL, tv.TEST_RUN, "static.%s.jsonl" % t) for t in pl.EXTERNAL_TOOLS]
        expected += [pt.ledger_relative(MODEL, tv.STATIC_RUN, n) for n in (pt.CORRECTNESS_FILE, pt.DYNAMIC_FILE)]
        expected += ["%s/%s/%s/generations.jsonl" % (pt.RAW_REL, run, MODEL) for run in self.repo.runs]
        for (block, variant), loop in self.repo.plan.items():
            expected += ["%s/%s/%s/repair/%s/%s" % (pt.INTERMEDIATE_REL, loop["owner"], MODEL, variant, name)
                         for name in ("wave_state.json", "state.jsonl")]
        expected += ["%s/%s/%s/repair/combined_feedback/%s" % (pt.INTERMEDIATE_REL, run, MODEL, name)
                     for run in (ORIGIN, SUCCESSOR) for name in ("state.jsonl", "request_rounds.json")]
        expected += [f["source_path"] for run in (pl.PILOT, tv.PILOT_ITER) for f in self.repo.runs[run][2]]
        expected += ["drivers/cpp/benchmarks/%s/cpu.cc" % b for b in (tv.PILOT_BENCH, tv.FULL_BENCH)]
        expected += [FROZEN_SPECS_REL]
        missing = sorted(set(expected) - set(read))
        self.assertEqual(missing, [])
        self.assertFalse([p for p in read if not (self.root / p).is_file()])
        # the specs module's shapes lie outside the synthetic root: identified in the provenance
        from thesis.enhanced_tests import specs as es

        self.assertEqual(dataset.provenance["enhanced_inputs"], OrderedDict([
            ("frozen_specs", FROZEN_SPECS_REL), ("shapes", None),
            ("shapes_raw_sha256", hashlib.sha256(es.SHAPES_PATH.read_bytes()).hexdigest())]))
        self.assertNotIn(SHAPES_REL, read)

    def test_enhanced_inputs_are_required_and_bound(self):
        from unittest import mock

        from thesis.enhanced_tests import specs as es

        # the shapes of a checkout that IS the analysed root are a files_read entry
        shapes = self.root / SHAPES_REL
        shapes.write_bytes(es.SHAPES_PATH.read_bytes())
        with mock.patch.object(es, "SHAPES_PATH", shapes), mock.patch.object(es, "_SHAPES_CACHE", None):
            dataset = self.build()
            self.assertEqual(dataset.provenance["files_read"][SHAPES_REL],
                             hashlib.sha256(shapes.read_bytes()).hexdigest())
            self.assertEqual(dataset.provenance["enhanced_inputs"]["shapes"], SHAPES_REL)
            shapes.unlink()
            self.refuses("missing input shapes")
        # the validator's cached shapes must be the recorded bytes
        with mock.patch.object(es, "_SHAPES_CACHE", OrderedDict([("other/00_benchmark", OrderedDict())])):
            self.refuses("cached input shapes differ")
        # without the frozen spec artifact the reader would silently use built-in specs only
        (self.root / FROZEN_SPECS_REL).unlink()
        self.refuses("missing frozen spec artifact")

    def test_drift_between_reads_refuses(self):
        files = nz.FilesRead(self.root)
        relative = pt.run_dir(pl.PILOT, MODEL) + "/assembly.jsonl"
        files.read(relative)
        files.note(relative)  # hashed once
        (self.root / relative).write_bytes(b"changed\n")
        with self.assertRaisesRegex(core.AnalysisRefused, "changed during the normalization"):
            files.read(relative)


@unittest.skipUnless(os.environ.get("STUDY_ANALYSIS_REAL") == "1", "real repository (minutes): STUDY_ANALYSIS_REAL=1")
class RealRepositoryTest(unittest.TestCase):
    def test_section_9_figures(self):
        from thesis.study_closure import core as closure

        context = closure.load_context(core.REPO_ROOT)
        dataset = nz.build_dataset(context.root, context.config, context.table,
                                   lineage_sha256=context.lineage.sha256)
        self.assertEqual(dataset.counts(), OrderedDict([
            ("base_cells", 1980), ("artifacts", 5460), ("tool_entries", 5460 * 11),
            ("findings", dataset.counts()["findings"]), ("enhanced_pairs", 109200), ("trajectories", 5940),
            ("generations", 5460)]))
        artifacts = dataset.rows("artifacts")
        self.assertEqual(Counter(r["block"] for r in dataset.rows("base_cells")),
                         Counter({"pilot": 396, "full_ext": 1584}))
        self.assertEqual(Counter((r["block"], r["iteration"]) for r in artifacts if r["iteration"]),
                         Counter({("pilot", 1): 358, ("pilot", 2): 189, ("full_ext", 1): 1879, ("full_ext", 2): 1054}))
        self.assertEqual(len(set(r["model_id"] for r in artifacts)), 11)
        benchmarks = OrderedDict((b, set(r["benchmark"] for r in artifacts if r["block"] == b)) for b in core.BLOCKS)
        self.assertEqual((len(benchmarks["pilot"]), len(benchmarks["full_ext"])), (12, 48))
        self.assertEqual(len(set(r["family"] for r in artifacts)), 12)
        terminal = OrderedDict((b, Counter(r["terminal_status"] for r in dataset.rows("trajectories")
                                           if r["block"] == b)) for b in core.BLOCKS)
        self.assertEqual(terminal["pilot"], Counter({"stopped_analysis_incomplete": 357, "stopped_budget": 123,
                                                     "stopped_clean": 324, "stopped_tests_pass": 384}))
        self.assertEqual(terminal["full_ext"], Counter({"stopped_analysis_incomplete": 1539, "stopped_budget": 725,
                                                        "stopped_clean": 959, "stopped_tests_pass": 1529}))
        pairs = dataset.rows("enhanced_pairs")
        block_of = dict((r["artifact_id"], r["block"]) for r in artifacts)
        self.assertEqual(Counter(block_of[p["artifact_id"]] for p in pairs),
                         Counter({"pilot": 18860, "full_ext": 90340}))
        self.assertEqual(Counter(block_of[p["artifact_id"]] for p in pairs if p["gated"]),
                         Counter({"pilot": 807, "full_ext": 483}))
        self.assertEqual(dataset.provenance["gated_groups"], 48)
        self.assertEqual(Counter(r["correctness_verdict"] for r in artifacts),
                         Counter({"pass": 4811, "build_failed": 328, "validation_failed": 288, "runtime_error": 10,
                                  "timeout": 23}))
        absent = [e for e in dataset.rows("tool_entries") if e["state"] == "ABSENT_INAPPLICABLE"]
        self.assertEqual((len(absent), set(block_of[e["artifact_id"]] for e in absent), set(e["stage"] for e in absent)),
                         (14, set(["pilot"]), set(["static"])))
        generations = dataset.rows("generations")
        self.assertEqual(Counter((g["kind"], g["timing_mode"]) for g in generations),
                         Counter({("base", "batch"): 1080, ("base", "direct"): 900, ("repair", "direct"): 3480}))
        self.assertEqual(Counter(g["kind"] for g in generations if g["reasoning_tokens"] is None),
                         Counter({"base": 180, "repair": 432}))
        self.assertEqual(dataset.provenance["targets_sha256"], context.lineage.targets_sha256)
        # disclosure of the frozen literal DIRTY rule (probed once on the real data, 170 artifacts)
        gap = dataset.provenance["dirty_only_from_gap_state_entries"]
        self.assertEqual(gap["artifacts"], OrderedDict([
            ("static/full_ext/BASE", 31), ("static/full_ext/REPAIR_CANDIDATES", 131), ("static/pilot/BASE", 7),
            ("static/pilot/REPAIR_CANDIDATES", 1)]))
        self.assertEqual(set(key.split("/", 3)[3] for key in gap["entries"]), set(["clang_tidy/NOT_ANALYZED"]))
        for relative in (FROZEN_SPECS_REL, SHAPES_REL):
            self.assertIn(relative, dataset.provenance["files_read"])
        self.assertEqual(dataset.provenance["enhanced_inputs"]["shapes"], SHAPES_REL)


if __name__ == "__main__":
    unittest.main()
