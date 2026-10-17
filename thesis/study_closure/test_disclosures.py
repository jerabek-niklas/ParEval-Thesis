"""Tests of the disclosure register.

Synthetic composite cells (a handful of OrderedDicts in the shape of
composite._cell), a synthetic census summary, fake phase-2 reports and
scans over small temp trees drive the pure computations; the register is
then built on a real Context (read-only: the small real artifacts - policy,
freeze, contracts, enhanced policy, stage history, one report per kind -
are read, the expensive shared results are the synthetic ones). The
minutes-long real operations (composite reconstruction, the full Infer
scan) run only under STUDY_CLOSURE_REAL=1.

    python3 -B -m unittest -v thesis.study_closure.test_disclosures
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt
from thesis.study_closure import core
from thesis.study_closure import disclosures as dc

REPO_ROOT = core.REPO_ROOT
MODEL = "claude_opus_5"
MODEL_2 = "qwen37_max"
SOURCE_RUN = pt.iteration_run(core.OWNERS[0], "test_feedback", 1)


def make_cell(block, iteration, sample_id, static=None, verdict=None, dynamic=None, enhanced=None,
              variant="static_feedback"):
    source_run = (core.PILOT if block == pc.PILOT_BLOCK else core.PARENT) if iteration == 0 \
        else pt.iteration_run(core.PILOT if block == pc.PILOT_BLOCK else core.OWNERS[0], variant, iteration)
    return OrderedDict([
        ("block", block), ("model_id", MODEL), ("variant", variant), ("iteration", iteration),
        ("sample_id", sample_id), ("execution_model", "serial"), ("benchmark", "sort/00"),
        ("source_run", source_run), ("owner", source_run), ("source_sha256", "ab" * 32), ("source_path", "x"),
        ("static", None if static is None else OrderedDict([
            ("owner", source_run), ("tools", OrderedDict(static)), ("supplemented", OrderedDict())])),
        ("correctness", None if verdict is None else OrderedDict([("owner", source_run), ("verdict", verdict)])),
        ("dynamic", None if dynamic is None else OrderedDict([
            ("owner", source_run),
            ("tools", OrderedDict((tool, OrderedDict([("analysis_state", state), ("ran", ran)]))
                                  for tool, (state, ran) in dynamic.items()))])),
        ("enhanced", None if enhanced is None else OrderedDict([
            ("owner", core.PHASE2), ("pairs", sum(enhanced.values())), ("statuses", OrderedDict(enhanced))])),
    ])


def synthetic_cells():
    return [
        make_cell(pc.PILOT_BLOCK, 0, "p0", static=[("compiler", "COMPLETED"), ("infer", "PARTIAL")], verdict="pass",
                 dynamic=OrderedDict([("asan_ubsan", ("COMPLETED", True)), ("tsan", ("NOT_APPLICABLE", False))]),
                 enhanced=OrderedDict([("pass", 3), ("baseline_incompatible", 1)])),
        make_cell(pc.PILOT_BLOCK, 1, "p1", static=[("compiler", "TIMEOUT"), ("infer", "TOOL_ERROR")],
                 verdict="build_failed", dynamic=OrderedDict([("asan_ubsan", ("TOOL_ERROR", True))]),
                 enhanced=OrderedDict([("pass", 2), ("numerically_unstable", 1)])),
        make_cell(pc.FULL_BLOCK, 0, "f0", enhanced=OrderedDict([("pass", 4)])),
        make_cell(pc.FULL_BLOCK, 2, "f2", static=[("compiler", "COMPLETED")], verdict="timeout",
                 dynamic=OrderedDict([("must", ("TIMEOUT", True))]), enhanced=OrderedDict([("fail", 1)]),
                 variant="combined_feedback"),
    ]


def synthetic_document(cells):
    persisted = REPO_ROOT / core.COMPOSITE_REL
    sha = "f" * 64
    if persisted.is_file():  # a persisted real composite must be THE document: borrow its identity
        sha = json.loads(persisted.read_text(encoding="utf-8")).get("composite_sha256")
    return OrderedDict([
        ("schema_version", pc.SCHEMA), ("run_id", core.PHASE2),
        ("population", OrderedDict([("base_cells", 2), ("per_run", OrderedDict([(core.PARENT, 1), (core.PILOT, 1)]))])),
        ("cells", pc._cell_counts(cells)), ("stage_coverage", pc._coverage(cells)),
        ("composite_sha256", sha)])


def synthetic_census():
    census = OrderedDict([("models", [MODEL]), ("base_cells", OrderedDict([("pilot", 1), ("full_ext", 1)])),
                          ("loops", []), ("non_model_terminal_statuses", ["stopped_baseline_incompatible"])])
    summary = OrderedDict([
        ("total_repair_loops_done", "2/2"),
        ("blocks", OrderedDict([
            (pc.PILOT_BLOCK, OrderedDict([("sample_states", OrderedDict([("stopped_budget", 1), ("stopped_clean", 1)]))])),
            (pc.FULL_BLOCK, OrderedDict([("sample_states", OrderedDict([("stopped_tests_pass", 1),
                                                                        ("stopped_baseline_incompatible", 2)]))]))])),
        ("base_cells", OrderedDict([("pilot", 1), ("full_ext", 1), ("total", 2)])),
        ("repair_conditions", ["r" * 64])])
    return census, summary


def fake_report(torn=0, repeated=0, stray=0):
    return OrderedDict([("status", core.PASS), ("checks", [
        OrderedDict([("check", dc.PHASE2_LEDGER_CHECK), ("status", core.PASS),
                     ("detail", OrderedDict([("stray", ["s"] * stray), ("archived_torn_tails", ["t"] * torn),
                                             ("temporary_files", [])]))]),
        OrderedDict([("check", "full_ext:full_ext_001:phase2_provenance"), ("status", core.PASS),
                     ("detail", OrderedDict([("rows", 1), ("unbound", 0), ("repeated_build_groups", repeated)]))]),
        OrderedDict([("check", "full_ext:%s:phase2_provenance" % SOURCE_RUN), ("status", core.PASS),
                     ("detail", OrderedDict([("rows", 1), ("unbound", 0), ("repeated_build_groups", 0)]))]),
    ])])


def _static_row(run, sample_id, seconds, model=MODEL):
    return OrderedDict([("schema_version", "static_analysis.v3"), ("run_id", run), ("model_id", model),
                        ("sample_id", sample_id), ("execution_model", "serial"),
                        ("tools", OrderedDict([("compiler", OrderedDict([("tool", "compiler"), ("ran", True),
                                                                          ("duration_seconds", 1.0),
                                                                          ("analysis_state", "COMPLETED")])),
                                               ("infer", OrderedDict([("tool", "infer"), ("ran", True),
                                                                       ("duration_seconds", seconds),
                                                                       ("analysis_state", "COMPLETED")]))]))])


def _supplement_row(tool, sample_id, seconds, model=MODEL):
    return OrderedDict([("schema_version", "successor_static_supplement.v1"), ("run_id", core.PHASE2),
                        ("candidate_source_run", SOURCE_RUN), ("model_id", model), ("sample_id", sample_id),
                        ("tool", tool), ("entry", OrderedDict([("tool", tool), ("ran", True),
                                                               ("duration_seconds", seconds),
                                                               ("analysis_state", "COMPLETED")]))])


def _write_jsonl(path, rows, torn=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row) + "\n" for row in rows)
    if torn:
        text += '{"schema_version": "static_analysis.v3", "run_id": "x", "tools": {"infer": {"dur'
    path.write_text(text, encoding="utf-8")


def temp_tree(root, outlier=4000.0, torn=False):
    """pilot_002 base dir with two static records (one outlier), a phase-2
    supplement dir with one infer and one llov row."""
    root = Path(root)
    inter = root / core.INTERMEDIATE_REL
    _write_jsonl(inter / core.PILOT / MODEL / pt.STATIC_FILE,
                 [_static_row(core.PILOT, "s_small", 12.5), _static_row(core.PILOT, "s_big", outlier)], torn=torn)
    _write_jsonl(inter / core.PHASE2 / MODEL / "supplements" / SOURCE_RUN / "static.infer.jsonl",
                 [_supplement_row("infer", "s_sup", 7.0)])
    _write_jsonl(inter / core.PHASE2 / MODEL / "supplements" / SOURCE_RUN / "static.llov.jsonl",
                 [_supplement_row("llov", "s_sup", 999999.0)])
    _write_jsonl(inter / core.PILOT / MODEL / dc.ASSEMBLY_FILE, [
        OrderedDict([("run_id", core.PILOT), ("model_id", MODEL), ("sample_id", "s_small"), ("assembled", True),
                     ("generation_truncated", False), ("assembly_condition_sha256", "a" * 64),
                     ("assembly_condition_version", "assembly_condition.v1"),
                     ("cleaning", OrderedDict([("used_fence", True), ("relocated_includes", []),
                                               ("braces_balanced", True), ("signature_found_in_output", True)]))]),
        OrderedDict([("run_id", core.PILOT), ("model_id", MODEL), ("sample_id", "s_big"), ("assembled", False),
                     ("generation_truncated", True), ("assembly_condition_sha256", "a" * 64),
                     ("assembly_condition_version", "assembly_condition.v1"),
                     ("cleaning", OrderedDict([("used_fence", False), ("relocated_includes", ["<x>"]),
                                               ("braces_balanced", False), ("dropped_leading_lines", 2)]))]),
    ])
    return root


def _write_json(root, relative, document):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def scope_tree(root):
    """Minimal persisted verification reports of every kind: the pilot
    post-run report, the parent report, two 003 and one 004 successor
    reports, two phase-2 reports."""
    _write_json(root, core.PILOT_POST_RUN_REL, {"schema_version": dc.POST_RUN_SCHEMA, "verifier_version": "verify_pilot_run.v1"})
    _write_json(root, core.RUN_REGISTRY[core.PARENT]["verification"], {"schema_version": dc.PARENT_SCHEMA, "scope": "BASE_ONLY"})
    for run, models in ((core.OWNERS[2], ("a", "b")), (core.OWNERS[3], ("c",))):
        for model in models:
            _write_json(root, core.RUN_REGISTRY[run]["verification"] + "/%s.successor_verification.json" % model,
                        {"schema_version": dc.SUCCESSOR_SCHEMA, "scope": "SUCCESSOR"})
    for model in ("a", "b"):
        _write_json(root, core.PHASE2_VERIFICATION_REL + "/%s.phase2_verification.json" % model,
                    {"schema_version": dc.PHASE2_SCHEMA, "scope": "PHASE2"})
    return Path(root)


class CellComputationTest(unittest.TestCase):

    def setUp(self):
        self.cells = synthetic_cells()

    def test_iteration_counts(self):
        result = dc.iteration_counts(self.cells)
        self.assertEqual(result["observed_max_iteration"], 2)
        self.assertEqual(result["per_block"], OrderedDict([
            ("pilot", OrderedDict([("iter0", 1), ("iter1", 1)])),
            ("full_ext", OrderedDict([("iter0", 1), ("iter2", 1)]))]))

    def test_static_gap_counts(self):
        result = dc.static_gap_counts(self.cells)
        self.assertEqual(result["cells_without_static"], OrderedDict([("pilot", 0), ("full_ext", 1)]))
        self.assertEqual(result["states"]["pilot"]["infer"], OrderedDict([("PARTIAL", 1), ("TOOL_ERROR", 1)]))
        self.assertEqual(result["states"]["pilot"]["compiler"], OrderedDict([("COMPLETED", 1), ("TIMEOUT", 1)]))
        self.assertEqual(result["states"]["full_ext"], OrderedDict([("compiler", OrderedDict([("COMPLETED", 1)]))]))
        subset = dc.gap_subset(result["states"], ("TIMEOUT", "TOOL_ERROR"))
        self.assertEqual(subset["pilot"], OrderedDict([("compiler", OrderedDict([("TIMEOUT", 1)])),
                                                       ("infer", OrderedDict([("TOOL_ERROR", 1)]))]))
        self.assertEqual(subset["full_ext"], OrderedDict())

    def test_dynamic_gap_counts(self):
        result = dc.dynamic_gap_counts(self.cells)
        self.assertEqual(result["cells_without_dynamic"], OrderedDict([("pilot", 0), ("full_ext", 1)]))
        asan = result["states"]["pilot"]["asan_ubsan"]
        self.assertEqual(asan["analysis_state"], OrderedDict([("COMPLETED", 1), ("TOOL_ERROR", 1)]))
        self.assertEqual(asan["ran"], OrderedDict([("true", 2)]))
        self.assertEqual(result["states"]["pilot"]["tsan"]["ran"], OrderedDict([("false", 1)]))
        self.assertEqual(result["states"]["full_ext"]["must"]["analysis_state"], OrderedDict([("TIMEOUT", 1)]))

    def test_correctness_counts(self):
        result = dc.correctness_counts(self.cells)
        self.assertEqual(result["verdicts"]["pilot"], OrderedDict([("build_failed", 1), ("pass", 1)]))
        self.assertEqual(result["verdicts"]["full_ext"], OrderedDict([("timeout", 1)]))
        self.assertEqual(result["cells_without_correctness"], OrderedDict([("pilot", 0), ("full_ext", 1)]))

    def test_enhanced_statuses_from_document(self):
        document = synthetic_document(self.cells)
        statuses = dc.enhanced_statuses(document)
        self.assertEqual(statuses["pairs"], OrderedDict([("pilot", 7), ("full_ext", 5)]))
        self.assertEqual(dc.status_per_block(statuses["statuses"], "numerically_unstable"),
                         OrderedDict([("pilot", 1), ("full_ext", 0)]))
        self.assertEqual(dc.status_per_block(statuses["statuses"], "baseline_incompatible"),
                         OrderedDict([("pilot", 1), ("full_ext", 0)]))


class ConfigComputationTest(unittest.TestCase):

    def test_reasoning_settings_exact_paths(self):
        models = [OrderedDict([("id", "a"), ("provider", "openai"), ("model_name", "m"), ("enabled", True),
                               ("api_key_env", "X"), ("reasoning_effort", "high")]),
                  OrderedDict([("id", "b"), ("provider", "openai_compatible"), ("model_name", "n"), ("enabled", True),
                               ("extra_body", OrderedDict([("enable_thinking", True), ("thinking_budget", 8192)]))]),
                  OrderedDict([("id", "c"), ("provider", "p"), ("model_name", "o"), ("enabled", False)]),
                  "not a model"]
        settings = dc.reasoning_settings(models)
        self.assertEqual(settings["a"]["reasoning"], OrderedDict([("reasoning_effort", "high")]))
        self.assertEqual(settings["b"]["reasoning"], OrderedDict([("extra_body.enable_thinking", True),
                                                                   ("extra_body.thinking_budget", 8192)]))
        self.assertEqual(settings["c"]["reasoning"], OrderedDict())
        self.assertNotIn("api_key_env", json.dumps(settings))
        self.assertEqual(list(dc.reasoning_settings(models, ["b", "a"]).keys()), ["b", "a"])
        with self.assertRaises(core.ClosureRefused):
            dc.reasoning_settings(models, ["a", "zzz"])

    def test_walk_keys_records_dict_valued_reasoning_settings(self):
        """A reasoning key whose value is an object (e.g. anthropic
        thinking: {type, budget_tokens}) is recorded at its path AND
        walked, so no model silently loses its reasoning setting."""
        found = OrderedDict()
        dc._walk_keys(OrderedDict([("id", "x"),
                                   ("thinking", OrderedDict([("type", "enabled"), ("budget_tokens", 1024)])),
                                   ("extra_body", OrderedDict([("thinking", OrderedDict([("effort", "high")]))]))]),
                      "", found)
        self.assertEqual(found, OrderedDict([
            ("thinking", OrderedDict([("type", "enabled"), ("budget_tokens", 1024)])),
            ("extra_body.thinking", OrderedDict([("effort", "high")])),
            ("extra_body.thinking.effort", "high")]))
        settings = dc.reasoning_settings([OrderedDict([("id", "a"), ("thinking", {"type": "enabled"})]),
                                          OrderedDict([("id", "b"), ("thinking", "adaptive")])])
        self.assertEqual(list(settings["a"]["reasoning"].keys()), ["thinking"])
        self.assertEqual(settings["b"]["reasoning"], OrderedDict([("thinking", "adaptive")]))
        self.assertEqual([m for m, e in settings.items() if not e["reasoning"]], [])

    def test_freeze_reasoning_flattens_the_plan(self):
        freeze = {"generation": {"effective_provider_plan": {
            "a": {"reasoning_configuration": {"effort": "medium", "thinking": "adaptive"}},
            "b": {"reasoning_configuration": {"extra_body": {"thinking_budget": 1}}}}}}
        result = dc.freeze_reasoning(freeze, ["a", "b", "c"])
        self.assertEqual(result["a"], OrderedDict([("effort", "medium"), ("thinking", "adaptive")]))
        self.assertEqual(result["b"], OrderedDict([("extra_body.thinking_budget", 1)]))
        self.assertEqual(result["c"], OrderedDict())


class ScanTest(unittest.TestCase):

    def test_infer_scan_finds_the_outlier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = temp_tree(tmp)
            self.assertEqual(dc.study_run_dirs(root), OrderedDict([(core.PILOT, "pilot")]))
            scan = dc.infer_scan(root)
            self.assertEqual(scan["files"], 3)
            self.assertEqual(scan["records"], 4)
            self.assertEqual(scan["infer_entries"], 3)
            self.assertEqual(scan["infer_entries_ran"], 3)
            self.assertEqual(scan["max_seconds"], 4000.0)
            self.assertEqual(scan["above_threshold"], 1)
            self.assertEqual(scan["above_threshold_entries"][0]["sample_id"], "s_big")
            self.assertEqual([e["sample_id"] for e in scan["top"]], ["s_big", "s_small", "s_sup"])
            self.assertEqual(scan["top"][2]["run"], core.PHASE2)
            self.assertEqual(scan["top"][2]["source_run"], SOURCE_RUN)
            self.assertTrue(scan["top"][0]["relative"].startswith(core.INTERMEDIATE_REL))
            self.assertEqual(scan["duration_keys_seen"], OrderedDict([("duration_seconds", 3)]))
            self.assertEqual(scan["wall_seconds_entries"], 0)
            self.assertEqual(scan["runs_scanned"], [core.PILOT])
            below = dc.infer_scan(root, threshold=5000)
            self.assertEqual(below["above_threshold"], 0)

    def test_infer_scan_is_fail_closed_on_a_torn_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = temp_tree(tmp, torn=True)
            with self.assertRaises(ValueError):
                dc.infer_scan(root)

    def test_infer_scan_counts_non_numeric_durations_and_carries_the_record_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = temp_tree(tmp)
            path = root / core.INTERMEDIATE_REL / core.PILOT / MODEL / pt.STATIC_FILE
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(rows[1]["sample_id"], "s_big")
            rows[1]["created_at_utc"] = "2026-10-11T08:23:35.079687Z"
            _write_jsonl(path, rows + [_static_row(core.PILOT, "s_bad", "n/a")])
            scan = dc.infer_scan(root)
            self.assertEqual(scan["infer_entries"], 4)
            self.assertEqual(scan["non_numeric_durations"], 1)
            self.assertNotIn("s_bad", [e["sample_id"] for e in scan["top"]])
            self.assertEqual(scan["above_threshold"], 1)
            self.assertEqual(scan["top"][0]["sample_id"], "s_big")
            self.assertEqual(scan["top"][0]["recorded_date"], "2026-10-11")
            self.assertEqual(scan["top"][1]["recorded_date"], "")
            self.assertNotIn("T08", json.dumps(scan))  # the date only, never the timestamp

    def test_stage_history_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(core.ClosureRefused, "missing artifact"):
                dc.stage_history(tmp)
            _write_jsonl(Path(tmp) / dc.STAGE_HISTORY_REL, [])
            with self.assertRaisesRegex(core.ClosureRefused, "empty"):
                dc.stage_history(tmp)

    def test_composite_source_refuses_a_differing_persisted_composite(self):
        with tempfile.TemporaryDirectory() as tmp:
            document = OrderedDict([("composite_sha256", "a" * 64)])
            entry = dc.composite_source(tmp, document)
            self.assertEqual((entry["persisted"], entry["raw_sha256"], entry["composite_sha256"]), (False, None, "a" * 64))
            _write_json(tmp, core.COMPOSITE_REL, {"composite_sha256": "b" * 64})
            with self.assertRaisesRegex(core.ClosureRefused, "differs"):
                dc.composite_source(tmp, document)
            _write_json(tmp, core.COMPOSITE_REL, {"composite_sha256": "a" * 64})
            entry = dc.composite_source(tmp, document)
            self.assertTrue(entry["persisted"])
            self.assertEqual(entry["raw_sha256"], core.raw_sha256(tmp, core.COMPOSITE_REL))

    def test_source_problems_reports_a_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.json").write_text("{}", encoding="utf-8")
            item = dc._item("pilot_label", dc.ARTIFACT_BOUND, [dc.source(tmp, "a.json")], OrderedDict())
            self.assertEqual(dc.source_problems(tmp, item), [])
            (Path(tmp) / "a.json").unlink()
            problems = dc.source_problems(tmp, item)
            self.assertEqual(len(problems), 1)
            self.assertIn("missing", problems[0])
            self.assertEqual(dc.source_problems(tmp, {"sources": [{"relative": "", "raw_sha256": "x"}]}),
                             ["source without path"])
            self.assertEqual(dc.source_problems(tmp, {"sources": [{"relative": "b.json", "raw_sha256": None}]}),
                             ["b.json: no raw sha256"])

    def test_assembly_pins_uniform_per_block(self):
        blocks = OrderedDict([("pilot", OrderedDict([("conditions", OrderedDict([("x" * 64, 2)]))])),
                              ("full_ext", OrderedDict([("conditions", OrderedDict([("y" * 64, 3)]))]))])
        self.assertEqual(dc.assembly_pins_uniform(blocks, {"pilot": "x" * 64, "full_ext": "y" * 64}),
                         OrderedDict([("pilot", True), ("full_ext", True)]))
        # the full_ext rows are compared with the parent's pin, never the pilot's
        self.assertEqual(dc.assembly_pins_uniform(blocks, {"pilot": "x" * 64, "full_ext": "x" * 64}),
                         OrderedDict([("pilot", True), ("full_ext", False)]))
        blocks["pilot"]["conditions"]["z" * 64] = 1
        self.assertFalse(dc.assembly_pins_uniform(blocks, {"pilot": "x" * 64, "full_ext": "y" * 64})["pilot"])
        self.assertEqual(dc.assembly_pins_uniform({}, {"pilot": "x" * 64}),
                         OrderedDict([("pilot", False), ("full_ext", False)]))

    def test_verification_scopes_read_every_report_and_refuse_foreign_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = scope_tree(tmp)
            scopes = dc.verification_scopes(root)
            entries = scopes["entries"]
            self.assertEqual(len(entries), 6)
            self.assertTrue(scopes["distinct"])
            self.assertEqual(scopes["retrospective"], OrderedDict())
            self.assertEqual((entries[0]["scope"], entries[0]["verifier_version"]), (None, "verify_pilot_run.v1"))
            self.assertEqual(len(entries[2]["artifacts"]), 3)
            self.assertEqual(len(entries[3]["artifacts"]), 2)
            self.assertEqual(entries[2]["scope"], "SUCCESSOR")
            successor_b = root / core.RUN_REGISTRY[core.OWNERS[2]]["verification"] / "b.successor_verification.json"
            # one report of the kind with another scope
            successor_b.write_text(json.dumps({"schema_version": dc.SUCCESSOR_SCHEMA, "scope": "OTHER"}), encoding="utf-8")
            with self.assertRaisesRegex(core.ClosureRefused, "disagree"):
                dc.verification_scopes(root)
            # a foreign document (any JSON object) replacing one report
            successor_b.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(core.ClosureRefused, "disagree"):
                dc.verification_scopes(root)
            successor_b.unlink()
            self.assertEqual(len(dc.verification_scopes(root)["entries"][2]["artifacts"]), 2)
            # a kind whose only report carries another kind's schema, an unknown schema, or no scope
            parent = core.RUN_REGISTRY[core.PARENT]["verification"]
            _write_json(root, parent, {"schema_version": dc.PHASE2_SCHEMA, "scope": "PHASE2"})
            with self.assertRaisesRegex(core.ClosureRefused, "expected"):
                dc.verification_scopes(root)
            _write_json(root, parent, {"schema_version": "unknown.v9", "scope": "X"})
            with self.assertRaisesRegex(core.ClosureRefused, "expected"):
                dc.verification_scopes(root)
            _write_json(root, parent, {"schema_version": dc.PARENT_SCHEMA})
            with self.assertRaisesRegex(core.ClosureRefused, "without a scope"):
                dc.verification_scopes(root)
            _write_json(root, parent, {"schema_version": dc.PARENT_SCHEMA, "scope": "BASE_ONLY"})
            self.assertTrue(dc.verification_scopes(root)["distinct"])
            # an empty report directory
            for path in (root / core.PHASE2_VERIFICATION_REL).glob("*.json"):
                path.unlink()
            with self.assertRaisesRegex(core.ClosureRefused, "no verification report"):
                dc.verification_scopes(root)

    def test_assembly_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = dc.assembly_scan(temp_tree(tmp))
            pilot = scan["blocks"]["pilot"]
            self.assertEqual(pilot["rows"], 2)
            self.assertEqual(pilot["files"], 1)
            self.assertEqual(pilot["assembled"], OrderedDict([("false", 1), ("true", 1)]))
            self.assertEqual(pilot["generation_truncated"], OrderedDict([("false", 1), ("true", 1)]))
            self.assertEqual(pilot["conditions"], OrderedDict([("a" * 64, 2)]))
            self.assertEqual(pilot["cleaning"], OrderedDict([("dropped_leading_lines", 1), ("relocated_includes", 1),
                                                             ("used_fence", 1)]))
            self.assertEqual(pilot["anomalies"], OrderedDict([("braces_balanced", 1)]))
            self.assertEqual(scan["blocks"]["full_ext"]["rows"], 0)

    def test_stage_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [OrderedDict([("stage", "static.main"), ("status", "invoked"), ("open_items", [])]),
                    OrderedDict([("stage", "static.main"), ("status", "invoked"), ("open_items", [])]),
                    OrderedDict([("stage", "static.main"), ("status", "completed"), ("open_items", [])]),
                    OrderedDict([("stage", "enhanced"), ("status", "invoked"), ("open_items", [])]),
                    OrderedDict([("stage", "enhanced"), ("status", "completed"), ("open_items", ["x"])])]
            _write_jsonl(Path(tmp) / dc.STAGE_HISTORY_REL, rows)
            history = dc.stage_history(tmp)
            self.assertEqual(history["rows"], 5)
            self.assertEqual(history["interrupted_invocations"], 1)
            main = history["stages"]["static.main"]
            self.assertEqual((main["invoked"], main["completed"], main["interrupted"], main["last_status"]),
                             (2, 1, 1, "completed"))
            self.assertEqual(history["stages"]["enhanced"]["last_open_items"], ["x"])
            self.assertEqual(history["stages"]["static.llov"]["invoked"], 0)
            self.assertIsNone(history["stages"]["static.llov"]["last_status"])
            self.assertEqual(list(history["stages"].keys()), list(pl.STAGES))

    def test_phase2_incidents(self):
        reports = OrderedDict([(MODEL, fake_report(torn=1, repeated=2)), (MODEL_2, fake_report(stray=1))])
        incidents = dc.phase2_incidents(reports)
        self.assertEqual(incidents["totals"], OrderedDict([("archived_torn_tails", 1), ("repeated_build_groups", 2),
                                                           ("stray", 1), ("temporary_files", 0)]))
        self.assertEqual(incidents["per_model"][MODEL]["provenance_checks"], 2)
        broken = fake_report()
        broken["checks"][0]["detail"]["stray"] = None
        with self.assertRaises(core.ClosureRefused):
            dc.phase2_incidents(OrderedDict([(MODEL, broken)]))
        with self.assertRaises(core.ClosureRefused):
            dc.phase2_incidents(OrderedDict([(MODEL, OrderedDict([("checks", [])]))]))
        bad_groups = fake_report()
        bad_groups["checks"][1]["detail"]["repeated_build_groups"] = None
        with self.assertRaises(core.ClosureRefused):
            dc.phase2_incidents(OrderedDict([(MODEL, bad_groups)]))


class RegisterCheckTest(unittest.TestCase):

    def _register(self, tmp):
        artifact = Path(tmp) / "a.json"
        artifact.write_text("{}", encoding="utf-8")
        items = [dc._item(item_id, dc.COMPUTED, [dc.source(tmp, "a.json")],
                          OrderedDict([("n", dc.count(1, "fixture")), ("t", dc.ev("a|b", "fixture"))]))
                 for item_id in dc.ITEM_IDS]
        infer = items[dc.ITEM_IDS.index("infer_runtime_outlier")]
        infer["evidence"]["above_threshold"] = dc.count(1, "fixture")
        infer["evidence"]["max_seconds"] = dc.number(4000.0, "fixture")
        infer["evidence"]["threshold_seconds"] = dc.number(dc.OUTLIER_SECONDS, "fixture")
        infer["evidence"]["top_entries"] = dc.ev([OrderedDict([("sample_id", "s")])], "fixture")
        infer["evidence"]["infer_entries"] = dc.count(3, "fixture")
        policy = items[0]
        policy["status"] = dc.ARTIFACT_BOUND
        policy["evidence"]["entries"] = dc.ev([OrderedDict([("id", "x"), ("satisfied", True)])], "fixture")
        register = OrderedDict([("schema_version", core.DISCLOSURES_SCHEMA), ("closure_id", core.CLOSURE_ID),
                                ("items", items)])
        register["register_sha256"] = core.self_hash(register, "register_sha256")
        return register

    def test_register_check_positive_and_negatives(self):
        with tempfile.TemporaryDirectory() as tmp:
            register = self._register(tmp)
            ok, detail = dc.register_check(tmp, register)
            self.assertTrue(ok, detail)
            self.assertEqual(detail["items"], len(dc.ITEM_IDS))
            self.assertTrue(dc.evidence_check(register)[0])
            self.assertTrue(dc.infer_outlier_check(register)[0])
            self.assertTrue(dc.policy_sources_check(register)[0])
            # a changed source
            (Path(tmp) / "a.json").write_text("{ }", encoding="utf-8")
            ok, detail = dc.register_check(tmp, register)
            self.assertFalse(ok)
            self.assertTrue(any("changed" in p for p in detail["problems"]), detail["problems"])
            (Path(tmp) / "a.json").write_text("{}", encoding="utf-8")
            # a None where a count is expected
            register["items"][2]["evidence"]["n"] = dc.count(OrderedDict([("pilot", None)]), "fixture")
            ok, detail = dc.register_check(tmp, register)
            self.assertFalse(ok)
            self.assertTrue(any("count" in p for p in detail["problems"]), detail["problems"])
            register["items"][2]["evidence"]["n"] = dc.count(1, "fixture")
            # an unavailable item
            register["items"][3] = dc._placeholder(dc.ITEM_IDS[3], dc.INPUT_UNAVAILABLE, "input unavailable: x")
            ok, detail = dc.register_check(tmp, register)
            self.assertFalse(ok)
            self.assertTrue(any(dc.INPUT_UNAVAILABLE in p for p in detail["problems"]), detail["problems"])
            # a wrong order
            register = self._register(tmp)
            register["items"].reverse()
            self.assertFalse(dc.register_check(tmp, register)[0])
            # the composite in memory is accepted in dry-run only
            register = self._register(tmp)
            register["items"][5]["sources"] = [OrderedDict([("relative", core.COMPOSITE_REL), ("raw_sha256", None),
                                                            ("composite_sha256", "f" * 64), ("persisted", False)])]
            self.assertTrue(dc.register_check(tmp, register)[0])
            self.assertFalse(dc.register_check(tmp, register, write_mode=True)[0])

    def test_no_numbers_from_memory_fails_without_a_source(self):
        register = OrderedDict([("items", [OrderedDict([("id", "x"), ("evidence", OrderedDict([
            ("n", OrderedDict([("value", 1), ("kind", "count")]))]))])])])
        problems = dc.evidence_problems(register)
        self.assertEqual(len(problems), 1)
        self.assertIn("no source", problems[0])
        self.assertFalse(dc.evidence_check(register)[0])
        bare = OrderedDict([("items", [OrderedDict([("id", "x"), ("evidence", OrderedDict([("n", 5)]))])])])
        self.assertTrue(any("not an evidence entry" in p for p in dc.evidence_problems(bare)))
        self.assertTrue(dc.evidence_problems(OrderedDict([("items", [OrderedDict([("id", "x"), ("evidence", {})])])])))
        with self.assertRaises(core.ClosureRefused):
            dc.ev(1, "")
        with self.assertRaises(core.ClosureRefused):
            dc.ev(1, "s", "weird")

    def test_infer_outlier_check_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            register = self._register(tmp)
            infer = register["items"][dc.ITEM_IDS.index("infer_runtime_outlier")]
            infer["evidence"]["above_threshold"] = dc.count(0, "fixture")
            infer["evidence"]["max_seconds"] = dc.number(12.0, "fixture")
            self.assertFalse(dc.infer_outlier_check(register)[0])
            register["items"][dc.ITEM_IDS.index("infer_runtime_outlier")] = dc._placeholder(
                "infer_runtime_outlier", dc.BUILD_FAILED, "x")
            self.assertFalse(dc.infer_outlier_check(register)[0])

    def test_render_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = dc.render_markdown(self._register(tmp))
        self.assertIn("## 13. Infer runtime outlier", text)
        self.assertIn("`infer_runtime_outlier`", text)
        self.assertIn("a\\|b", text)
        self.assertIn("| evidence | value | source |", text)
        self.assertEqual(text.count("| source | raw sha256 |"), len(dc.ITEM_IDS))


class RegisterOnRealContextTest(unittest.TestCase):
    """The register on the real Context with synthetic shared results: the
    small real artifacts are read, nothing expensive runs, nothing is
    written."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tree = temp_tree(cls.tmp.name)
        cls.infer = dc.infer_scan(tree)
        cls.assembly = dc.assembly_scan(tree)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def context(self, complete=True):
        ctx = core.load_context(REPO_ROOT)
        ctx.cache["infer_scan"] = json.loads(json.dumps(self.infer), object_pairs_hook=OrderedDict)
        # the scan's files must be real artifacts for the source pins
        real = "%s/%s/%s/%s" % (core.INTERMEDIATE_REL, core.PILOT, MODEL, pt.STATIC_FILE)
        for entry in ctx.cache["infer_scan"]["top"] + ctx.cache["infer_scan"]["above_threshold_entries"]:
            entry["relative"] = real
        ctx.cache["assembly_scan"] = self.assembly
        if complete:
            cells = synthetic_cells()
            census, summary = synthetic_census()
            ctx.cache["composite_cells"] = cells
            ctx.cache["composite_document"] = synthetic_document(cells)
            ctx.cache["census"] = census
            ctx.cache["census_summary"] = summary
            ctx.cache["phase2_reports"] = OrderedDict([(MODEL, fake_report(torn=1)), (MODEL_2, fake_report())])
        return ctx

    def test_register_and_section_pass(self):
        ctx = self.context()
        section = dc.collect(ctx)
        register = ctx.cache["disclosure_register"]
        failing = [(i["id"], i["status"], i["evidence"].get("problem", {}).get("value"))
                   for i in register["items"] if i["status"] not in dc.FINAL_STATUSES]
        self.assertEqual(failing, [])
        self.assertEqual(section.status, core.PASS, [c for c in section.checks if c["status"] != core.PASS])
        self.assertEqual([c["check"] for c in section.checks],
                         ["disclosures:inputs_available", "disclosures:register_built", "disclosures:policy_sources_ok",
                          "disclosures:infer_outlier_found", "disclosures:no_numbers_from_memory"])
        self.assertEqual([i["id"] for i in register["items"]], list(dc.ITEM_IDS))
        self.assertEqual(core.self_hash(register, "register_sha256"), register["register_sha256"])
        self.assertEqual(section.data["register"]["items"], len(dc.ITEM_IDS))
        by_id = OrderedDict((i["id"], i) for i in register["items"])
        self.assertEqual(by_id["max_two_repair_iterations"]["evidence"]["observed_max_iteration"]["value"], 2)
        self.assertEqual(by_id["max_two_repair_iterations"]["evidence"]["configured_max_iterations"]["value"],
                         pl.MAX_ITERATIONS)
        self.assertEqual(by_id["baseline_incompatibilities"]["evidence"]["repair_stopped_baseline_incompatible"]["value"],
                         OrderedDict([("pilot", 0), ("full_ext", 2)]))
        self.assertEqual(by_id["numerical_tolerance"]["evidence"]["numerically_unstable"]["value"],
                         OrderedDict([("pilot", 1), ("full_ext", 0)]))
        self.assertEqual(by_id["infer_runtime_outlier"]["evidence"]["above_threshold"]["value"], 1)
        self.assertEqual(by_id["phase2_operational_incidents"]["evidence"]["incident_totals"]["value"]["archived_torn_tails"], 1)
        self.assertEqual(by_id["excluded_aborted_parent_repair"]["evidence"]["per_run"]["value"]
                         [core.EXCLUDED_RUNS[0]]["phase2_targets_with_this_source_run"], 0)
        self.assertEqual(len(by_id["reasoning_policy_differences"]["evidence"]["per_model"]["value"]), len(core.MODELS))
        self.assertNotIn("api_key", json.dumps(register).lower().replace("api_key_env", ""))
        text = dc.render_markdown(register)
        self.assertIn("## 1. ", text)
        self.assertEqual(section.data["markdown_bytes"], len(text.encode("utf-8")))
        self.assertTrue(json.dumps(register, default=str))

    def test_missing_producers_fail_closed(self):
        ctx = self.context(complete=False)
        section = dc.collect(ctx)
        self.assertEqual(section.status, core.FAIL)
        self.assertIn("disclosures:inputs_available", section.failing())
        self.assertIn("disclosures:register_built", section.failing())
        register = ctx.cache["disclosure_register"]
        unavailable = [i["id"] for i in register["items"] if i["status"] == dc.INPUT_UNAVAILABLE]
        self.assertIn("static_analysis_gaps", unavailable)
        self.assertIn("phase2_operational_incidents", unavailable)
        self.assertNotIn("pilot_label", unavailable)
        self.assertTrue(dc.evidence_check(register)[0])

    def test_items_without_composite_use_real_artifacts(self):
        ctx = self.context()
        inputs = dc.gather_inputs(ctx)
        item = dc.item_single_tool(ctx, inputs)
        self.assertEqual(item["status"], dc.ARTIFACT_BOUND)
        self.assertEqual(len(item["sources"]), 2 + len(dc.TOOL_VALIDATION_RELS))
        self.assertTrue(item["evidence"]["low_confidence_prefix"]["value"])
        label = dc.item_pilot_label(ctx, inputs)
        self.assertIs(label["evidence"]["may_be_presented_as_full_60_benchmark_study"]["value"], False)
        scopes = dc.item_scopes(ctx, inputs)
        self.assertTrue(scopes["evidence"]["scopes_distinct"]["value"])
        entries = scopes["evidence"]["scopes"]["value"]
        self.assertEqual(len(entries), 6)
        self.assertEqual(entries[2]["run_ids"], [core.OWNERS[2], core.OWNERS[3]])
        # EVERY persisted report of a kind is read and pinned (counted from the directories)
        successor_reports = sum(len(list((REPO_ROOT / core.RUN_REGISTRY[run]["verification"]).glob("*.json")))
                                for run in (core.OWNERS[2], core.OWNERS[3]))
        phase2_reports = len(list((REPO_ROOT / core.PHASE2_VERIFICATION_REL).glob("*.json")))
        self.assertEqual(len(entries[2]["artifacts"]), successor_reports)
        self.assertEqual(len(entries[3]["artifacts"]), phase2_reports)
        self.assertEqual(len(scopes["sources"]), 2 + successor_reports + phase2_reports)
        self.assertEqual(entries[-1]["scope"], core.RETROSPECTIVE_SCOPE)
        self.assertEqual(entries[0]["schema_version"], dc.POST_RUN_SCHEMA)
        self.assertNotIn("33/33", json.dumps(entries))

    def test_items_refuse_contradicting_inputs(self):
        """A builder whose static requirement text would contradict the
        computed evidence refuses instead of reporting a self-contradictory
        item (one generation per base cell, the pilot label)."""
        ctx = self.context()
        inputs = dc.gather_inputs(ctx)
        item = dc.item_one_generation(ctx, inputs)
        self.assertEqual(item["status"], dc.COMPUTED)
        # the synthetic composite holds one base cell per block: reported, not refused (the population section owns it)
        self.assertEqual(item["evidence"]["composite_base_equals_expected_population"]["value"],
                         OrderedDict([("pilot", False), ("full_ext", False)]))
        contradicted = OrderedDict(inputs)
        contradicted["pilot_contract"] = copy.deepcopy(inputs["pilot_contract"])
        contradicted["pilot_contract"]["population"]["num_samples_per_prompt"] = 2
        with self.assertRaisesRegex(core.ClosureRefused, "samples per prompt"):
            dc.item_one_generation(ctx, contradicted)
        contradicted = OrderedDict(inputs)
        contradicted["freeze"] = copy.deepcopy(inputs["freeze"])
        contradicted["freeze"]["population"]["samples_per_prompt"] = None
        with self.assertRaisesRegex(core.ClosureRefused, "samples per prompt"):
            dc.item_one_generation(ctx, contradicted)
        forged = OrderedDict(inputs)
        forged["policy"] = copy.deepcopy(inputs["policy"])
        forged["policy"]["may_be_presented_as_full_60_benchmark_study"] = True
        with self.assertRaises(core.ClosureRefused):
            dc.item_pilot_label(ctx, forged)
        forged["policy"] = copy.deepcopy(inputs["policy"])
        forged["policy"]["pilot_label"] = "changed"  # the self-hash no longer reproduces: not FRESH
        with self.assertRaisesRegex(core.ClosureRefused, "FRESH"):
            dc.item_pilot_label(ctx, forged)
        # the cleaning item compares every block with its own contract pin
        cleaning = dc.item_cleaning(ctx, inputs)
        pins = cleaning["evidence"]["assembly_condition_pins"]["value"]
        self.assertEqual(pins["pilot"], inputs["pilot_contract"]["conditions"]["assembly_condition_sha256"])
        self.assertEqual(pins["full_ext"], inputs["parent_contract"]["conditions"]["assembly_condition_sha256"])
        self.assertEqual(cleaning["evidence"]["assembly_condition_uniform_and_pinned"]["value"],
                         OrderedDict([("pilot", False), ("full_ext", False)]))  # synthetic rows, no full_ext rows
        # the infer item carries the record date of the longest entry (synthetic rows: none)
        infer = dc.item_infer(ctx, inputs)
        self.assertEqual(infer["evidence"]["longest_entry_recorded_date"]["value"], "")
        self.assertNotIn("2026-10-11", infer["narrative"])


@unittest.skipUnless(os.environ.get("STUDY_CLOSURE_REAL") == "1", "set STUDY_CLOSURE_REAL=1 (tens of seconds)")
class RealScanTest(unittest.TestCase):

    def test_real_infer_scan_finds_the_outlier(self):
        scan = dc.infer_scan(REPO_ROOT)
        self.assertGreaterEqual(scan["above_threshold"], 1)
        self.assertGreater(scan["max_seconds"], dc.OUTLIER_SECONDS)
        self.assertEqual(scan["non_numeric_durations"], 0)


if __name__ == "__main__":
    unittest.main()
