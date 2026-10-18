"""Tests of the study-analysis validation (validate.py) on a synthetic,
internally consistent study: two blocks (the pilot one on the BL-01
benchmark), two models, three execution models, three variants with native
and continued loops (final iterations 0, 1, 2), an ABSENT_INAPPLICABLE slot,
compiler-subsumed tool rejections (some carrying blocking findings: DIRTY
under the frozen F01 rule only), static DIRTY artifacts of several tools,
auto-closed artifacts, a gated enhanced spec group, findings of every kind,
the persisted composite, the census, the state ledgers, a target table,
estimates (frozen metrics and the post-freeze addendum X01-X06 with the
DESIGN2 contract keys), tables, figures and the input manifest. The clean
world PASSES every check; one injected contradiction per check FAILS exactly
that check.

    python3 -B -m unittest -v thesis.study_analysis.test_validate
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter, OrderedDict
from itertools import combinations
from pathlib import Path
from unittest import mock

from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.study_analysis import core, manifest, validate
from thesis.study_analysis.test_preflight import HEAD, closure_document, git_state, write
from thesis.recovery_successor_004 import census as cs
from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import targets as pt

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS2 = ("claude_fable_5", "claude_opus_5")
EMS = core.EXECUTION_MODELS
BENCH = OrderedDict([("pilot", core.BL01_BENCHMARK), ("full_ext", "sort/40_sort_beta")])
SCOPE = OrderedDict([
    ("static", OrderedDict([("compiler", EMS), ("gcc_analyzer", EMS), ("clang_tidy", EMS), ("cppcheck", EMS),
                            ("infer", ("serial", "mpi")), ("parcoach", ("mpi",)), ("llov", ("omp",))])),
    ("dynamic", OrderedDict([("asan_ubsan", EMS), ("tsan", ("omp",)), ("memcheck", ("serial", "omp")),
                             ("must", ("mpi",))])),
])
SPECS = ('["s1"]', '["s2"]')
ORIGIN = cs.ORIGIN
SUPPLEMENTED_TOOLS = ("gcc_analyzer", "clang_tidy", "cppcheck", "infer", "parcoach", "llov")


def h(text):
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)


def loop_owner(block, model, variant):
    """(owner, continued) of a synthetic loop."""
    if block == "pilot":
        return core.PILOT, False
    if model == MODELS2[1] and variant == "static_feedback":
        return core.OWNERS[2], True
    if model == MODELS2[1] and variant == "test_feedback":
        return ORIGIN, False
    return core.OWNERS[3], False


def source_run(block, owner, continued, variant, k):
    if k == 0:
        return core.BLOCK_BASE_RUN[block]
    if continued and k == 1:
        return pt.iteration_run(ORIGIN, variant, 1)
    return pt.iteration_run(owner, variant, k)


def final_of(i, variant):
    return {"static_feedback": i % 3, "test_feedback": (i // 2) % 2, "combined_feedback": (i + 2) % 3}[variant]


def status_of(i, final):
    if final == core.MAX_ITERATIONS:
        return "stopped_budget"
    if final == 0:
        return "stopped_clean" if i % 2 else "stopped_tests_pass"
    return "stopped_tests_pass" if i % 2 == 0 else "stopped_analysis_incomplete"


class World:
    """The synthetic study and every validation input."""

    def __init__(self, root):
        self.root = Path(root)
        self.rows = OrderedDict((name, []) for name in core.SCHEMAS)
        self.cells = []
        self.loops = OrderedDict()
        self.targets = OrderedDict()
        self._build()
        self._ledgers()
        self._inputs()

    # -- artifacts -----------------------------------------------------------------------------
    def _artifact(self, block, model, em, sample_id, variant, k, run, loop, absent_llov=False):
        aid = core.artifact_id(block, model, run, sample_id)
        benchmark = BENCH[block]
        hv = h(aid)
        verdict = ("pass", "pass", "validation_failed", "build_failed", "timeout")[hv % 5]
        record_owner = core.PILOT if block == "pilot" else run
        backfilled = block == "full_ext" and variant == "static_feedback" and k >= 1
        stage_owner = core.PHASE2 if backfilled else record_owner
        entries, findings = [], []
        for stage, tools in SCOPE.items():
            for tool, models in tools.items():
                applicable = em in models
                owner = record_owner if stage == "static" else stage_owner
                if stage == "static" and block == "full_ext" and tool in SUPPLEMENTED_TOOLS:
                    if variant == "test_feedback" and k >= 1:
                        owner = core.PHASE2
                    elif loop[1] and k == 1 and tool == "llov":
                        owner = core.OWNERS[2]
                found = []
                state, raw = "COMPLETED", None
                if not applicable:
                    state = "ABSENT_INAPPLICABLE" if (absent_llov and tool == "llov") else "NOT_APPLICABLE"
                elif verdict == "build_failed":
                    if tool == "compiler":
                        found.append(("build-error", "build", "error", "reported_blocking"))
                    elif tool == "clang_tidy":
                        state, raw = "NOT_ANALYZED", "TOOL_ERROR"
                        if hv % 2:   # printed before the front-end error: DIRTY under the frozen rule only (X02)
                            found.append(("bugprone-narrowing-conversions", "other", "warning", "reported_blocking"))
                    elif stage == "dynamic":
                        state = "TOOL_ERROR"
                else:
                    if tool == "gcc_analyzer" and hv % 4 == 0:
                        state = "PARTIAL"
                        if hv % 3 == 0:   # a PARTIAL entry's finding counts under both readings
                            found.append(("-Wanalyzer-malloc-leak", "memory", "warning", "reported_blocking"))
                    if tool == "clang_tidy" and hv % 6 == 5:
                        found.append(("bugprone-easily-swappable-parameters", "other", "warning", "reported_blocking"))
                    if tool == "cppcheck" and hv % 2:
                        found.append(("style", "other", "style", "non_blocking"))
                    if tool == "cppcheck" and hv % 9 == 4:
                        found.append(("nullPointer", "null_deref", "error", "reported_blocking"))
                    if tool == "tsan" and hv % 5 == 1:
                        found.append(("tsan-data-race", "race", "error", "reported_blocking"))
                    if tool == "parcoach" and hv % 3 == 0:
                        found.append(("parcoach-collective", "mpi_usage", "warning", "low_confidence"))
                counts = Counter(kind for _, _, _, kind in found)
                entries.append(OrderedDict([
                    ("artifact_id", aid), ("stage", stage), ("tool", tool), ("applicable", applicable),
                    ("state", state), ("ran", state not in core.INAPPLICABLE_STATES),
                    ("duration_seconds", 1.5 if state not in core.INAPPLICABLE_STATES else None),
                    ("num_findings", len(found)), ("num_reported_blocking", counts["reported_blocking"]),
                    ("num_low_confidence", counts["low_confidence"]), ("num_non_blocking", counts["non_blocking"]),
                    ("owner", owner), ("_raw", raw)]))
                for check_id, family, severity, kind in found:
                    findings.append(OrderedDict([("artifact_id", aid), ("stage", stage), ("tool", tool),
                                                 ("check_id", check_id), ("family", family), ("severity", severity),
                                                 ("kind", kind), ("line", 7)]))
        statuses = []
        for spec in SPECS:
            if spec == SPECS[1] and block == "full_ext" and em == "mpi":
                status = "baseline_incompatible"
            elif verdict == "build_failed":
                status = "build_failed"
            else:
                status = "pass" if (h(aid + spec) % 3) else "fail"
            statuses.append(status)
            self.rows["enhanced_pairs"].append(OrderedDict([
                ("artifact_id", aid), ("spec_key", spec), ("size", 1), ("pattern", "random"), ("spec_source", "static"),
                ("status", status), ("gated", status in core.ENHANCED_GATED), ("duration_seconds", 0.1)]))
        tally = Counter(statuses)
        gated = sum(n for s, n in tally.items() if s in core.ENHANCED_GATED)
        valid = len(statuses) - gated
        static = [e for e in entries if e["stage"] == "static"]
        dynamic = [e for e in entries if e["stage"] == "dynamic"]
        cleaning = OrderedDict((flag, False) for flag in core.CLEANING_FLAGS)
        cleaning["used_fence"] = bool(hv % 2)
        cleaning["auto_closed"] = hv % 7 == 0
        artifact = OrderedDict([
            ("artifact_id", aid), ("cell_id", core.cell_id(block, model, sample_id)), ("block", block),
            ("model_id", model), ("benchmark", benchmark), ("family", core.family_of(benchmark)),
            ("execution_model", em), ("sample_id", sample_id), ("variant", variant or ""), ("iteration", k),
            ("source_run", run), ("loop_owner", "" if k == 0 else loop[0]), ("source_sha256", "%064x" % h(aid + "src")),
            ("generation_success", True), ("assembled", True), ("generation_truncated", hv % 11 == 0)])
        for flag in core.CLEANING_FLAGS:
            artifact["clean_" + flag] = cleaning[flag]
        artifact["clean_any"] = any(v for f, v in cleaning.items() if f != "used_fence")
        artifact["clean_any_including_fence"] = any(cleaning.values())
        supplemented = OrderedDict((e["tool"], e["owner"]) for e in static if e["owner"] != record_owner)
        artifact.update([
            ("build_ok", verdict != "build_failed"), ("correctness_verdict", verdict),
            ("correctness_owner", stage_owner), ("static_owner", record_owner),
            ("static_supplemented_by", supplemented), ("dynamic_owner", stage_owner),
            ("enhanced_owner", core.PILOT if block == "pilot" else core.PHASE2),
            ("static_three_state", validate.three_state([e for e in static if e["tool"] != "compiler"])[0]),
            ("dynamic_three_state", validate.three_state(dynamic)[0]),
            ("compile_error", any(e["tool"] == "compiler" and e["num_reported_blocking"] for e in static)),
            ("low_confidence_any", any(e["num_low_confidence"] for e in entries)),
            ("static_analysis_complete", validate.three_state([e for e in static if e["tool"] != "compiler"])[1]),
            ("dynamic_analysis_complete", validate.three_state(dynamic)[1]),
            ("enh_pairs", len(statuses)), ("enh_valid", valid), ("enh_gated", gated)])
        for status in core.ENHANCED_STATUSES:
            if status not in core.ENHANCED_GATED:
                artifact["enh_" + status] = tally.get(status, 0)
        artifact["enh_all_pass"] = None if valid == 0 else int(tally.get("pass", 0) == valid)
        self.rows["artifacts"].append(artifact)
        for e in entries:
            raw = e.pop("_raw")
            e["_composite"] = raw or e["state"]
        self.rows["tool_entries"].extend(entries)
        self.rows["findings"].extend(findings)
        self.rows["generations"].append(OrderedDict([
            ("artifact_id", aid), ("kind", "base" if k == 0 else "repair"), ("provider", "anthropic"),
            ("success", True), ("timing_mode", "batch" if k == 0 else "direct"),
            ("duration_seconds", None if k == 0 else 2.5), ("input_tokens", 100), ("output_tokens", 50),
            ("reasoning_tokens", None if model == MODELS2[1] else 10), ("request_chars", None if k == 0 else 1000),
            ("finish_reason", "stop")]))
        cell = OrderedDict([
            ("block", block), ("model_id", model), ("variant", variant), ("iteration", k), ("sample_id", sample_id),
            ("execution_model", em), ("benchmark", benchmark), ("source_run", run),
            ("owner", core.PILOT if block == "pilot" else run), ("source_sha256", artifact["source_sha256"]),
            ("source_path", "x/%s.hpp" % sample_id),
            ("static", OrderedDict([("owner", record_owner),
                                    ("tools", OrderedDict((e["tool"], e["_composite"]) for e in static
                                                          if e["state"] != "ABSENT_INAPPLICABLE")),
                                    ("supplemented", supplemented)])),
            ("correctness", OrderedDict([("owner", stage_owner), ("verdict", verdict)])),
            ("dynamic", OrderedDict([("owner", stage_owner), ("tools", OrderedDict(
                (e["tool"], OrderedDict([("analysis_state", e["_composite"]), ("ran", e["ran"])])) for e in dynamic))])),
            ("enhanced", OrderedDict([("owner", artifact["enhanced_owner"]), ("pairs", len(statuses)),
                                      ("statuses", pc.counts(tally))])),
        ])
        self.cells.append(cell)
        return artifact

    def _build(self):
        i = 0
        for block in core.BLOCKS:
            family, name = BENCH[block].split("/")
            for model in MODELS2:
                for em in EMS:
                    sample_id = "%s__%s__%s__%s__sample_0" % (model, family, name, em)
                    base = self._artifact(block, model, em, sample_id, None, 0, core.BLOCK_BASE_RUN[block], (None, False),
                                          absent_llov=(block == "pilot" and model == MODELS2[0] and em == "mpi"))
                    self.rows["base_cells"].append(OrderedDict([
                        ("cell_id", base["cell_id"]), ("block", block), ("model_id", model),
                        ("benchmark", base["benchmark"]), ("family", base["family"]), ("execution_model", em),
                        ("sample_id", sample_id), ("base_run", base["source_run"]),
                        ("source_sha256", base["source_sha256"]), ("bl01", base["benchmark"] == core.BL01_BENCHMARK)]))
                    if block == "full_ext":
                        self.targets.setdefault((model, core.PARENT), [None, None, 0, core.PARENT, None, "base", []])[6] \
                            .append(base)
                    for variant in core.VARIANTS:
                        owner, continued = loop_owner(block, model, variant)
                        final = final_of(i, variant)
                        status = status_of(i, final)
                        ids = [base["artifact_id"], "", ""]
                        for k in range(1, final + 1):
                            run = source_run(block, owner, continued, variant, k)
                            a = self._artifact(block, model, em, sample_id, variant, k, run, (owner, continued))
                            ids[k] = a["artifact_id"]
                            if block == "full_ext":
                                self.targets.setdefault((model, run), [model, variant, k, run, owner,
                                                                       "continued" if continued else "native", []])[6] \
                                    .append(a)
                        statuses = ["active"] * final + [status] + [""] * (core.MAX_ITERATIONS - final)
                        verdict = base["correctness_verdict"] if variant != "static_feedback" else None
                        self.rows["trajectories"].append(OrderedDict([
                            ("trajectory_id", core.trajectory_id(base["cell_id"], variant)), ("cell_id", base["cell_id"]),
                            ("block", block), ("model_id", model), ("variant", variant), ("loop_owner", owner),
                            ("loop_kind", "continued" if continued else "native"), ("final_iteration", final),
                            ("terminal_status", status), ("stop_reason", "reason %d" % final),
                            ("status_iter0", statuses[0]), ("status_iter1", statuses[1]),
                            ("status_iter2", statuses[2]), ("test_verdict_final", verdict or ""),
                            ("artifact_iter0", ids[0]), ("artifact_iter1", ids[1]), ("artifact_iter2", ids[2]),
                            ("final_artifact", ids[final]), ("request_rounds", final)]))
                        self.loops.setdefault((block, model, variant), []).append(
                            (sample_id, final, status, "reason %d" % final, verdict))
                    i += 1

    def _ledgers(self):
        for (block, model, variant), samples in self.loops.items():
            owner, continued = loop_owner(block, model, variant)
            directory = "thesis/results/intermediate/%s/%s/repair/%s" % (owner, model, variant)
            wave = OrderedDict([("run_id", owner), ("model_id", model), ("variant", variant), ("phase", "done"),
                                ("iteration", 2), ("repair_condition_sha256", "c" * 64)])
            if continued:
                wave["predecessor_run_id"] = ORIGIN
            write(self.root, directory + "/wave_state.json", wave)
            own, origin, own_rounds, origin_rounds = [], [], OrderedDict(), OrderedDict()
            for sample_id, final, status, reason, verdict in samples:
                for k in range(final + 1):
                    last = k == final
                    row = OrderedDict([("run_id", ORIGIN if continued and k == 0 else owner), ("model_id", model),
                                       ("variant", variant), ("sample_id", sample_id), ("iteration", k),
                                       ("status", status if last else "active"),
                                       ("stop_reason", reason if last else "continue"),
                                       ("test_verdict", verdict if last else None)])
                    (origin if continued and k == 0 else own).append(row)
                for k in range(1, final + 1):
                    target = origin_rounds if continued and k == 1 else own_rounds
                    target.setdefault(sample_id, OrderedDict())[str(k)] = 1
            write(self.root, directory + "/state.jsonl", "".join(json.dumps(r) + "\n" for r in own))
            write(self.root, directory + "/request_rounds.json", own_rounds)
            if continued:
                base = "thesis/results/intermediate/%s/%s/repair/%s" % (ORIGIN, model, variant)
                write(self.root, base + "/state.jsonl", "".join(json.dumps(r) + "\n" for r in origin))
                write(self.root, base + "/request_rounds.json", origin_rounds)

    def census(self):
        loops = []
        for (block, model, variant), samples in self.loops.items():
            owner, continued = loop_owner(block, model, variant)
            loops.append(OrderedDict([
                ("block", block), ("model", model), ("variant", variant), ("owner", owner),
                ("expected_cells", len(samples)), ("state", "TERMINAL"), ("terminal", True),
                ("kind", "continued" if continued else "native"), ("phase", "done"), ("iteration", 2),
                ("repair_condition_sha256", "c" * 64), ("samples", len(samples)),
                ("status_counts", OrderedDict(sorted(Counter(s[2] for s in samples).items())))]))
        base = OrderedDict((block, sum(1 for c in self.rows["base_cells"] if c["block"] == block)) for block in core.BLOCKS)
        return OrderedDict([("models", list(MODELS2)), ("base_cells", base), ("loops", loops),
                            ("non_model_terminal_statuses", list(core.NON_MODEL_TERMINAL))])

    def table(self):
        targets = []
        for (model, run), (m, variant, k, source, owner, kind, artifacts) in self.targets.items():
            targets.append(pt.Target(OrderedDict([
                ("target_id", "%s/%s" % (model, run)), ("model_id", model), ("block", "full_ext"),
                ("variant", variant), ("iteration", k), ("source_run", run), ("loop_owner", owner),
                ("loop_kind", kind), ("assembly", OrderedDict()), ("sample_count", len(artifacts)),
                ("samples", [OrderedDict([("sample_id", a["sample_id"]), ("execution_model", a["execution_model"]),
                                          ("benchmark", a["benchmark"]), ("source_sha256", a["source_sha256"]),
                                          ("source_path", "x")]) for a in artifacts])])))

        class Table:
            sha256 = "2" * 64

        table = Table()
        table.targets = targets
        return table

    def composite(self, cells=None, lineage_sha="1" * 64, targets_sha="2" * 64, plan_totals=None):
        cells = self.cells if cells is None else cells
        per_run = Counter(c["source_run"] for c in cells if c["iteration"] == 0)
        document = OrderedDict([
            ("schema_version", pc.SCHEMA), ("run_id", core.PHASE2), ("lineage_sha256", lineage_sha),
            ("targets_sha256", targets_sha), ("model_ids", list(MODELS2)),
            ("population", OrderedDict([("base_cells", sum(per_run.values())),
                                        ("per_run", OrderedDict(sorted(per_run.items()))), ("derived_base_cells", 0)])),
            ("derived_lineages", []), ("cells", pc._cell_counts(cells)), ("stage_coverage", pc._coverage(cells)),
            ("plan_totals", plan_totals if plan_totals is not None else OrderedDict([("enhanced", {"items": 0})])),
        ])
        document = json.loads(json.dumps(document), object_pairs_hook=OrderedDict)
        document["composite_sha256"] = canonical_sha256(document)
        return document

    def write_composite(self, document):
        write(self.root, pc.DOCUMENT_REL, document)
        self.composite_sha = document["composite_sha256"]

    def refresh_manifest(self):
        with mock.patch.object(core, "git_state", lambda root: git_state()):
            self.manifest = manifest.input_manifest(self.root, self.dataset)

    def _inputs(self):
        for e in self.rows["tool_entries"]:
            e.pop("_composite", None)
        write(self.root, core.METHODOLOGY_REL, (REPO_ROOT / core.METHODOLOGY_REL).read_bytes())
        write(self.root, core.ADDENDUM_REL, (REPO_ROOT / core.ADDENDUM_REL).read_bytes())
        write(self.root, core.PACKAGE_REL + "/module.py", "x = 1\n")
        self.write_composite(self.composite())
        raw = hashlib.sha256((self.root / pc.DOCUMENT_REL).read_bytes()).hexdigest()
        write(self.root, core.CLOSURE_REL, closure_document(raw, self.composite_sha))
        write(self.root, core.ACCEPTANCE_REL, OrderedDict([("status", "ACCEPTED")]))
        read = OrderedDict()
        for relative in ("thesis/results/intermediate/pilot_002/%s/assembly.jsonl" % MODELS2[0],
                         "thesis/results/raw/full_ext_001/%s/generations.jsonl" % MODELS2[0]):
            write(self.root, relative, "{}\n")
            read[relative] = hashlib.sha256(b"{}\n").hexdigest()
        self.census_result = self.census()
        self.dataset = core.Dataset(self.rows, OrderedDict([
            ("targets_sha256", "2" * 64), ("lineage_sha256", "1" * 64),
            ("census_digest", canonical_sha256(cs.summary(self.census_result))),
            ("readers", ["thesis.recovery_successor_005.composite"]), ("files_read", read)]))
        self.methodology = core.load_methodology(self.root)
        self.addendum = core.load_addendum(self.root, methodology=self.methodology)
        self.notes = validate.table_note_texts(self.addendum)
        self.estimates = make_estimates(self.dataset)
        self.rerun = [copy.deepcopy(e) for e in self.estimates if e["p_value"] is not None]
        self.tables = [OrderedDict([
            ("id", "T1_test"), ("title", "Test table"), ("population", "BASE"), ("unit", "artifact"),
            ("notes", []), ("ci_note", None),
            ("columns", [OrderedDict([("key", "model"), ("header", "Model"), ("align", "l")]),
                         OrderedDict([("key", "n"), ("header", "Q06 n/N"), ("align", "r")]),
                         OrderedDict([("key", "pct"), ("header", "Q06 %"), ("align", "r")])]),
            ("rows", [OrderedDict([("model", "all"), ("n", "3/6"), ("pct", "50.0%")]),
                      OrderedDict([("model", "models"), ("n", "11"), ("pct", "-")])]),
            ("footnotes", [])]),
            OrderedDict([
                ("id", "T2_structured"), ("title", "Structured cells"), ("population", "FINAL"),
                ("unit", "base cell"), ("notes", ["BL01: " + self.notes["BL01"]]), ("ci_note", "95% CI"),
                ("columns", [OrderedDict([("key", "block"), ("header", "Block"), ("align", "l"), ("kind", "block")]),
                             OrderedDict([("key", "q06"), ("header", "Q06 % (n/N)"), ("align", "r"), ("kind", "rate")]),
                             OrderedDict([("key", "gain"), ("header", "R04 pp (n/N)"), ("align", "r"), ("kind", "diff")]),
                             OrderedDict([("key", "ci"), ("header", "95% CI"), ("align", "r"), ("kind", "ci")]),
                             OrderedDict([("key", "n"), ("header", "Cells"), ("align", "r"), ("kind", "count")])]),
                ("rows", [OrderedDict([
                    ("block", "pilot"),
                    ("q06", OrderedDict([("numerator", 3), ("denominator", 6), ("value", 0.5), ("ci_low", 0.3),
                                         ("ci_high", 0.7), ("ci_degenerate", False),
                                         ("source", OrderedDict([("metric_id", "Q06"), ("population", "BASE"),
                                                                 ("block", "pilot"), ("strata", OrderedDict())]))])),
                    ("gain", OrderedDict([("numerator", -1), ("denominator", 6), ("value", -1 / 6.0),
                                          ("ci_low", None), ("ci_high", None)])),
                    ("ci", OrderedDict([("ci_low", 0.3), ("ci_high", 0.7)])), ("n", 6)]),
                    OrderedDict([("block", "full_ext"), ("q06", None),
                                 ("gain", OrderedDict([("numerator", 0), ("denominator", 0), ("value", None),
                                                       ("ci_low", None), ("ci_high", None)])),
                                 ("ci", None), ("n", 0)])]),
                ("footnotes", [OrderedDict([("mark", "a"), ("text", "pilot label")])])])]
        self.figures = [OrderedDict([("id", "F1_test"), ("title", "Test figure"), ("kind", "bars"),
                                     ("data_columns", ["x", "y"]), ("data_rows", [OrderedDict([("x", 1), ("y", 2)])]),
                                     ("axes", OrderedDict()), ("notes", [])])]
        self.refresh_manifest()

    # -- running -------------------------------------------------------------------------------
    def fake_composite_document(self, root, config, table, lineage_sha, plan_totals, population=None, cells=None,
                                models=None):
        return self.composite(cells=cells, lineage_sha=lineage_sha, targets_sha=table.sha256, plan_totals=plan_totals)

    def validate(self, **overrides):
        arguments = OrderedDict([
            ("root", self.root), ("config", None), ("table", self.table()), ("dataset", self.dataset),
            ("estimates", self.estimates), ("tables", self.tables), ("figures", self.figures),
            ("manifest", self.manifest), ("composite_cells", self.cells), ("estimates_rerun", self.rerun),
            ("census_result", self.census_result)])
        arguments.update(overrides)
        patches = [mock.patch.object(core, "MODELS", MODELS2),
                   mock.patch.object(core, "EXPECTED_COMPOSITE_SHA256", self.composite_sha),
                   mock.patch.object(validate, "_tool_scope", lambda config: SCOPE),
                   mock.patch.object(validate.pc, "composite_document", self.fake_composite_document)]
        for p in patches:
            p.start()
        try:
            return validate.validate(**arguments)
        finally:
            for p in reversed(patches):
                p.stop()


F06_LABELS = (("tsan+llov", "race"), ("must+parcoach", "mpi_usage+deadlock"), ("asan_ubsan+memcheck", "memory"),
              ("gcc_analyzer+cppcheck", "memory+null_deref+uninitialized"))


def make_estimates(dataset):
    """A complete, internally consistent estimate set (every methodology
    metric id) built with the validation's own engine (Recompute.expected).
    The engine is pinned to hand counts (test_recompute_matches_hand_counts,
    test_new_metric_families_match_hand_counts) and cross-checked against the
    independent implementation metrics.py on the metrics fixture
    (MetricsCrossCheckTest), so the clean-world PASS is not self-referential
    alone."""
    index = validate.Index(dataset)
    engine = validate.Recompute(index)
    addendum = engine.addendum()
    post_freeze = set(core.addendum_metric_ids(addendum))
    prefix = validate.post_freeze_prefix(addendum)
    out = []

    def rec(metric, population, block, strata, statistic="share"):
        stub = OrderedDict([("metric_id", metric), ("population", population), ("block", block),
                            ("strata", OrderedDict(strata))])
        facts = engine.expected(stub)
        e = OrderedDict([("metric_id", metric), ("population", population), ("block", block),
                         ("strata", OrderedDict(strata)), ("numerator", facts["numerator"]),
                         ("denominator", facts["denominator"]), ("value", facts["value"]),
                         ("ci_low", None), ("ci_high", None), ("ci_method", None), ("replicates", None),
                         ("p_value", None), ("p_holm", None), ("reject_holm", None),
                         ("note", prefix + "synthetic" if metric in post_freeze else None),
                         ("statistic", statistic), ("post_freeze", metric in post_freeze), ("ci_degenerate", None),
                         ("p_resolution", None), ("p_holm_resolution", None)])
        for key, value in facts.items():
            if not key.startswith("_"):
                e.setdefault(key, value)
        out.append(e)
        return e

    combos = sorted(set((f["tool"], f["family"], f["kind"]) for f in index.findings))
    for block in core.BLOCKS + (core.COMPOSITE,):
        for metric in ("Q01", "Q02", "Q03", "Q05", "Q06", "Q07", "Q09", "Q10", "E02", "E05", "F03", "F04",
                       "S03", "D03"):
            rec(metric, "BASE", block, [])
        rec("Q06", "BASE", block, [("model_id", MODELS2[0])])
        rec("Q06", "BASE", block, [("execution_model", "omp"), ("family", "sort")])
        rec("E01", "ENH_PAIRS(BASE)", block, [])
        rec("Q04", "BASE", block, [("flag", "any")])
        for verdict in core.CORRECTNESS_VERDICTS:
            rec("Q08", "BASE", block, [("verdict", verdict)])
            for k in range(core.MAX_ITERATIONS + 1):
                rec("Q08", "GENERATED", block, [("iteration", k), ("verdict", verdict)])
        for state in core.THREE_STATE:
            rec("F01", "BASE", block, [("state", state)])
            rec("F02", "BASE", block, [("state", state)])
        for status in core.ENHANCED_STATUSES:
            rec("E03", "ENH_PAIRS(BASE)", block, [("status", status)])
        rec("E04", "ENH_PAIRS(BASE)", block, [])
        for stage, (m_state, m_cover) in (("static", ("S01", "S02")), ("dynamic", ("D01", "D02"))):
            for tool in SCOPE[stage]:
                for state in core.TOOL_STATES:
                    rec(m_state, "BASE", block, [("tool", tool), ("state", state)])
                rec(m_cover, "BASE", block, [("tool", tool)])
        for variant in core.VARIANTS:
            for metric in ("Q06", "E02", "Q05"):
                rec(metric, "FINAL", block, [("variant", variant)])
                for k in range(core.MAX_ITERATIONS + 1):
                    rec(metric, "STEP", block, [("variant", variant), ("step", k)])
            for endpoint in validate.PRIMARY_ENDPOINTS:
                for metric in ("R02", "R03", "R04"):
                    rec(metric, "FINAL", block, [("endpoint", endpoint), ("variant", variant)],
                        statistic="difference" if metric == "R04" else "share")
                for k in range(core.MAX_ITERATIONS + 1):
                    rec("G02", "STEP", block, [("endpoint", endpoint), ("variant", variant), ("step", k)])
            for metric in ("R07", "R08", "R09", "R10"):
                rec(metric, "TRAJECTORIES", block, [("variant", variant)], statistic="mean" if metric == "R10" else "share")
            for status in core.TERMINAL_STATUSES:
                rec("R06", "TRAJECTORIES", block, [("variant", variant), ("status", status)])
                for k in range(core.MAX_ITERATIONS + 1):
                    rec("R06", "TRAJECTORIES", block, [("variant", variant), ("status", status), ("iteration", k)])
            rec("G01", "FINAL", block, [("variant", variant)])
            rec("G01", "FINAL", block, [("variant", variant), ("comparison", "G01-E05(BASE)")], statistic="difference")
            for endpoint, states in validate.R01_STATES.items():
                for x in states:
                    for y in states:
                        rec("R01", "FINAL", block, [("endpoint", endpoint), ("variant", variant),
                                                    ("transition", "%s->%s" % (x, y))])
            for quantity in validate.C01_QUANTITIES:
                rec("C01", "REPAIR_CANDIDATES", block, [("variant", variant), ("quantity", quantity)],
                    statistic="mean")
            for field in validate.TOKEN_FIELDS:
                rec("C02", "REPAIR_CANDIDATES", block, [("variant", variant), ("quantity", field)], statistic="mean")
            rec("C03", "REPAIR_CANDIDATES", block, [("variant", variant)], statistic="median")
            for quantity in ("per_1M_output_tokens", "per_100_requests"):
                rec("C05", "FINAL", block, [("variant", variant), ("quantity", quantity)], statistic="scaled_rate")
        for field in validate.TOKEN_FIELDS:
            rec("C02", "BASE", block, [("quantity", field)], statistic="mean")
        for stage in SCOPE.values():
            for tool in stage:
                for rule in validate.OUTLIER_RULES:
                    rec("C04", "GENERATED", block, [("tool", tool), ("outlier_rule", rule)], statistic="median")
        for endpoint in validate.PRIMARY_ENDPOINTS:
            for v1, v2 in combinations(core.VARIANTS, 2):
                rec("R05", "FINAL", block, [("endpoint", endpoint), ("comparison", "%s-%s" % (v1, v2))],
                    statistic="difference")
        for population, variants in (("BASE", (None,)), ("GENERATED", (None,)), ("FINAL", core.VARIANTS)):
            for variant in variants:
                for tool, family, kind in combos:
                    for quantity in validate.F05_QUANTITIES:
                        strata = ([("variant", variant)] if variant else []) + [
                            ("tool", tool), ("family", family), ("kind", kind), ("quantity", quantity)]
                        rec("F05", population, block, strata, statistic="count")
        for pair, klass in F06_LABELS:
            rec("F06", "GENERATED", block, [("pair", pair), ("class", klass)], statistic="agreement")
        # the post-freeze addendum X01-X06 (DESIGN2 section 1 shapes)
        for endpoint in validate.PRIMARY_ENDPOINTS:
            for variant in core.VARIANTS:
                rec("X01", "FINAL", block, [("endpoint", endpoint), ("variant", variant)], statistic="difference")
            for v1, v2 in combinations(core.VARIANTS, 2):
                rec("X01", "FINAL", block, [("endpoint", endpoint), ("comparison", "%s-%s" % (v1, v2))],
                    statistic="difference")
        for state in core.THREE_STATE:
            rec("X02", "BASE", block, [("state", state)])
            for em in EMS:
                rec("X02", "BASE", block, [("execution_model", em), ("state", state)])
            for variant in core.VARIANTS:
                rec("X02", "FINAL", block, [("variant", variant), ("state", state)])
        for tool in core.STATIC_ANALYSIS_TOOLS:
            rec("X03", "BASE", block, [("tool", tool), ("quantity", validate.X03_ONLY)])
            for check_id in engine.x03_top()[tool]:
                rec("X03", "BASE", block, [("tool", tool), ("check_id", check_id), ("quantity", validate.X03_FINDINGS)],
                    statistic="count")
                rec("X03", "BASE", block, [("tool", tool), ("check_id", check_id),
                                           ("quantity", validate.X03_ARTIFACTS)])
        for state in validate.X04_STATES:
            rec("X04", "BASE", block, [("state", state)])
            for variant in core.VARIANTS:
                rec("X04", "FINAL", block, [("variant", variant), ("state", state)])
        for variant in core.VARIANTS:
            rec("X05", "TRAJECTORIES", block, [("variant", variant)], statistic="mean")
            for k in range(core.MAX_ITERATIONS + 1):
                rec("X05", "TRAJECTORIES", block, [("variant", variant), ("iteration", k)])
            for q in engine.r01_labels("Q06"):
                for h in engine.r01_labels("E02"):
                    rec("X06", "FINAL", block, [("variant", variant), ("transition", q), ("heldout_transition", h)])
    primary = [e for e in out if e["block"] == core.COMPOSITE and e["metric_id"] in validate.PRIMARY_METRICS
               and set(e["strata"]) in ({"endpoint", "variant"}, {"endpoint", "comparison"})]
    p_values = (0.001, 0.2, 0.03, 0.004, 0.5, 0.012, 0.9, 0.04, 0.0002, 0.07, 0.6, 0.008)
    for e, p in zip(primary, p_values):
        e["p_value"] = p
        e["ci_method"] = validate.CI_METHOD
        e["replicates"] = 10000
        e["ci_low"] = max(-1.0, e["value"] - 0.1)
        e["ci_high"] = min(1.0, e["value"] + 0.1)
        e["ci_degenerate"] = e["ci_low"] == e["ci_high"]
        e["p_resolution"] = 2.0 / 10000
        # Holm-order running maximum of (m - rank + 1) * 2/B: m * 2/B for every hypothesis (hand value)
        e["p_holm_resolution"] = 12 * 2.0 / 10000
    adjusted = validate.holm_adjusted(OrderedDict((i, e["p_value"]) for i, e in enumerate(primary)))
    for i, e in enumerate(primary):
        e["p_holm"] = adjusted[i]
        e["reject_holm"] = adjusted[i] <= 0.05
    return out


def check(result, name):
    for entry in result["checks"]:
        if entry["check"] == name:
            return entry
    raise AssertionError("no check %s" % name)


def find(estimates, metric, population, block, **strata):
    for e in estimates:
        if (e["metric_id"], e["population"], e["block"]) == (metric, population, block) and \
                json.dumps(e["strata"], sort_keys=True) == json.dumps(strata, sort_keys=True):
            return e
    raise AssertionError("no estimate %s %s %s %s" % (metric, population, block, strata))


class ValidateTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="study_analysis_validate_")
        self.world = World(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assertFails(self, result, name, fragment=None):
        entry = check(result, name)
        self.assertEqual(entry["status"], "FAIL", "%s unexpectedly passed: %s" % (name, json.dumps(entry, default=str)))
        self.assertEqual(result["status"], "FAIL")
        if fragment is not None:
            self.assertIn(fragment, json.dumps(entry["detail"], default=str))

    def assertOnlyFails(self, result, names, fragment=None):
        failing = [c["check"] for c in result["checks"] if c["status"] != "PASS"]
        for name in names:
            self.assertFails(result, name, fragment)
        unexpected = [n for n in failing if n not in names]
        self.assertEqual(unexpected, [], json.dumps([c for c in result["checks"] if c["check"] in unexpected],
                                                    default=str)[:3000])

    # -- the clean world ------------------------------------------------------------------------
    def test_clean_world_passes_every_check(self):
        result = self.world.validate()
        failing = [c for c in result["checks"] if c["status"] != "PASS"]
        self.assertEqual(failing, [], json.dumps(failing, indent=1, default=str)[:6000])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["schema_version"], core.VALIDATION_SCHEMA)
        self.assertEqual(result["validation_sha256"], core.self_hash(result, "validation_sha256"))
        binding = check(result, "composite_binding")["detail"]
        self.assertGreater(binding["subsumed_rejections"], 0)
        self.assertGreater(check(result, "estimate_recompute")["detail"]["recomputed"], 500)
        self.assertEqual(check(result, "enhanced_gates")["detail"]["gated_groups"], 1)
        self.assertEqual(check(result, "primary_family")["detail"]["hypotheses"], 12)
        self.assertEqual(result, self.world.validate())  # deterministic

    def test_validation_never_raises(self):
        result = validate.validate(self.tmp, None, None, None, None, None, None, None)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(all(c["status"] == "FAIL" for c in result["checks"]))

    # -- independent sources --------------------------------------------------------------------
    def test_inputs_bound_to_table_lineage_and_census(self):
        self.world.dataset.provenance["targets_sha256"] = "9" * 64
        self.assertFails(self.world.validate(), "inputs_bound", "targets_sha256")
        self.world.dataset.provenance["targets_sha256"] = "2" * 64
        self.world.dataset.provenance["lineage_sha256"] = "8" * 64
        self.assertFails(self.world.validate(), "inputs_bound", "lineage_sha256")

    def test_one_candidate_count_in_the_composite_fails(self):
        document = self.world.composite()
        document["cells"]["candidates"]["full_ext"]["static_feedback"]["iter1"] += 1
        document["composite_sha256"] = canonical_sha256(OrderedDict((k, v) for k, v in document.items()
                                                                    if k != "composite_sha256"))
        self.world.write_composite(document)
        self.world.refresh_manifest()
        result = self.world.validate()
        self.assertOnlyFails(result, ["counts_composite", "composite_binding"])
        self.assertIn("cells.candidates.full_ext.static_feedback.iter1",
                      json.dumps(check(result, "counts_composite")["detail"]))

    def test_one_status_count_in_the_stage_coverage_fails(self):
        document = self.world.composite()
        document["stage_coverage"]["full_ext"]["enhanced"]["statuses"]["pass"] -= 1
        document["composite_sha256"] = canonical_sha256(OrderedDict((k, v) for k, v in document.items()
                                                                    if k != "composite_sha256"))
        self.world.write_composite(document)
        self.world.refresh_manifest()
        self.assertOnlyFails(self.world.validate(), ["counts_stage_coverage", "composite_binding"])

    def test_one_census_status_count_fails(self):
        census = copy.deepcopy(self.world.census_result)
        counts = census["loops"][0]["status_counts"]
        key = list(counts)[0]
        counts[key] -= 1
        counts["stopped_budget"] = counts.get("stopped_budget", 0) + 1
        self.world.dataset.provenance["census_digest"] = canonical_sha256(cs.summary(census))
        self.world.refresh_manifest()   # the manifest describes the dataset it was built over
        result = self.world.validate(census_result=census)
        self.assertOnlyFails(result, ["counts_census"])

    def test_trajectory_contradicting_its_state_ledger_fails(self):
        relative = "thesis/results/intermediate/%s/%s/repair/static_feedback/state.jsonl" % (core.PILOT, MODELS2[0])
        path = self.world.root / relative
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows[-1]["stop_reason"] = "something else"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.assertOnlyFails(self.world.validate(), ["trajectories_ledger"], "stop_reason")

    def test_request_rounds_follow_the_continued_overlay(self):
        histories = validate.ledger_histories(self.world.root, self.world.census_result)
        continued = [(key, value) for key, value in histories.items()
                     if key[1] == MODELS2[1] and key[2] == "static_feedback" and key[0] == "full_ext"]
        self.assertTrue(continued)
        for key, (owner, history, rounds, kind) in continued:
            self.assertEqual(owner, core.OWNERS[2])
            self.assertEqual(kind, "continued")
            self.assertEqual([r["iteration"] for r in history], list(range(len(history))))
            self.assertEqual(rounds, len(history) - 1)
            if len(history) > 1:
                self.assertEqual(history[0]["run_id"], ORIGIN)
                self.assertEqual(history[1]["run_id"], core.OWNERS[2])
        trajectory = [t for t in self.world.rows["trajectories"] if t["model_id"] == MODELS2[1]
                      and t["variant"] == "static_feedback" and t["block"] == "full_ext" and t["final_iteration"] == 2][0]
        trajectory["request_rounds"] = 1
        # estimates over the changed dataset: only the ledger (the independent source) contradicts it
        self.world.estimates = make_estimates(self.world.dataset)
        self.assertOnlyFails(self.world.validate(), ["trajectories_ledger"], "request_rounds")

    def test_composite_binding_detects_one_verdict(self):
        cells = copy.deepcopy(self.world.cells)
        cells[3]["correctness"]["verdict"] = "timeout" if cells[3]["correctness"]["verdict"] != "timeout" else "pass"
        result = self.world.validate(composite_cells=cells)
        self.assertOnlyFails(result, ["composite_binding"], "verdict")

    def test_composite_binding_detects_one_tool_state(self):
        cells = copy.deepcopy(self.world.cells)
        cells[0]["static"]["tools"]["cppcheck"] = "TIMEOUT"
        self.assertOnlyFails(self.world.validate(composite_cells=cells), ["composite_binding"], "cppcheck")
        cells = copy.deepcopy(self.world.cells)
        cells[0]["enhanced"]["statuses"] = OrderedDict([("pass", 2)]) if cells[0]["enhanced"]["statuses"] != {"pass": 2} \
            else OrderedDict([("fail", 2)])
        self.assertFails(self.world.validate(composite_cells=cells), "composite_binding", "enhanced statuses")

    # -- structure -------------------------------------------------------------------------------------
    def test_duplicate_pair_fails_uniqueness(self):
        pairs = self.world.dataset.tables["enhanced_pairs"]  # the Dataset holds its own row lists
        pairs.append(copy.deepcopy(pairs[0]))
        self.assertFails(self.world.validate(), "uniqueness", "(artifact, spec_key)")

    def test_foreign_owner_fails_ownership(self):
        artifact = [a for a in self.world.rows["artifacts"] if a["block"] == "full_ext"][0]
        artifact["correctness_owner"] = core.OWNERS[1]
        self.assertFails(self.world.validate(), "ownership", "correctness_owner")
        artifact = [a for a in self.world.rows["artifacts"] if a["block"] == "pilot"][0]
        artifact["enhanced_owner"] = core.PHASE2
        self.assertFails(self.world.validate(), "ownership", "enhanced_owner")

    def test_excluded_run_file_fails(self):
        self.world.dataset.provenance["files_read"]["thesis/results/raw/%s/m/generations.jsonl"
                                                    % core.EXCLUDED_RUNS[0]] = "0" * 64
        self.assertFails(self.world.validate(), "excluded_runs", core.EXCLUDED_RUNS[0])
        self.assertTrue(validate._excluded_path("thesis/results/intermediate/full_ext_001/m/repair/x/state.jsonl"))
        self.assertFalse(validate._excluded_path("thesis/results/intermediate/full_ext_001/m/static_analysis.jsonl"))

    def test_block_mixing_fails(self):
        cell = self.world.rows["base_cells"][0]
        cell["bl01"] = not cell["bl01"]
        self.assertFails(self.world.validate(), "block_separation", "bl01")
        cell["bl01"] = not cell["bl01"]
        candidate = [a for a in self.world.rows["artifacts"] if a["block"] == "pilot" and a["iteration"] == 1][0]
        candidate["source_run"] = pt.iteration_run(core.OWNERS[3], candidate["variant"], 1)
        self.assertFails(self.world.validate(), "block_separation", "is not a pilot iteration run")

    def test_artifact_outside_the_target_table_fails(self):
        table = self.world.table()
        target = [t for t in table.targets if t.iteration == 1][0]
        target.samples.popitem()
        self.assertFails(self.world.validate(table=table), "table_targets", "outside the target table")

    def test_enhanced_columns_must_equal_the_pair_rows(self):
        artifact = self.world.rows["artifacts"][5]
        artifact["enh_fail"] += 1
        self.assertFails(self.world.validate(), "dataset_consistency", "enh_fail")

    def test_finding_counts_must_equal_the_entry(self):
        entry = [e for e in self.world.rows["tool_entries"] if e["tool"] == "cppcheck" and e["num_non_blocking"]][0]
        entry["num_non_blocking"] = 0
        self.assertFails(self.world.validate(), "dataset_consistency", "finding rows")

    def test_three_state_recomputed(self):
        artifact = [a for a in self.world.rows["artifacts"] if a["static_three_state"] == "NO_FINDING_INCOMPLETE"][0]
        artifact["static_three_state"] = "CLEAN_COMPLETE"
        self.assertFails(self.world.validate(), "applicability", "static_three_state")

    def test_inapplicable_never_a_gap(self):
        rows = [OrderedDict([("applicable", True), ("state", "COMPLETED"), ("num_reported_blocking", 0)]),
                OrderedDict([("applicable", False), ("state", "NOT_APPLICABLE"), ("num_reported_blocking", 0)]),
                OrderedDict([("applicable", False), ("state", "ABSENT_INAPPLICABLE"), ("num_reported_blocking", 0)])]
        self.assertEqual(validate.three_state(rows), ("CLEAN_COMPLETE", True))
        rows.append(OrderedDict([("applicable", True), ("state", "PARTIAL"), ("num_reported_blocking", 0)]))
        self.assertEqual(validate.three_state(rows), ("NO_FINDING_INCOMPLETE", False))
        rows.append(OrderedDict([("applicable", False), ("state", "COMPLETED"), ("num_reported_blocking", 3)]))
        self.assertEqual(validate.three_state(rows)[0], "NO_FINDING_INCOMPLETE")
        rows.append(OrderedDict([("applicable", True), ("state", "PARTIAL"), ("num_reported_blocking", 1)]))
        self.assertEqual(validate.three_state(rows)[0], "DIRTY")
        entry = [e for e in self.world.rows["tool_entries"] if e["applicable"] and e["tool"] == "infer"][0]
        entry["state"] = "NOT_APPLICABLE"
        self.assertFails(self.world.validate(), "applicability", "inapplicable state")

    def test_mixed_gate_group_fails(self):
        pair = [p for p in self.world.rows["enhanced_pairs"] if p["gated"]][0]
        pair["gated"] = False
        pair["status"] = "pass"
        self.assertFails(self.world.validate(), "enhanced_gates", "mixed gate group")

    def test_final_artifact_must_follow_the_ledger_iteration(self):
        trajectory = [t for t in self.world.rows["trajectories"] if t["final_iteration"] == 1][0]
        trajectory["final_artifact"] = trajectory["artifact_iter0"]
        self.assertFails(self.world.validate(), "trajectory_structure", "final_artifact")
        trajectory["final_artifact"] = trajectory["artifact_iter1"]
        trajectory["status_iter0"] = "stopped_clean"
        self.assertFails(self.world.validate(), "trajectory_structure", "before the final iteration")

    # -- estimates --------------------------------------------------------------------------------------
    def test_unknown_strata_key_fails_the_schema(self):
        estimates = copy.deepcopy(self.world.estimates)
        estimates[0]["strata"]["colour"] = "red"
        self.assertFails(self.world.validate(estimates=estimates), "estimates_schema", "colour")
        estimates = copy.deepcopy(self.world.estimates)
        estimates.append(copy.deepcopy(find(estimates, "F05", "BASE", "pilot", tool="compiler", family="build",
                                            kind="reported_blocking", quantity="findings")))
        result = self.world.validate(estimates=estimates)
        self.assertFails(result, "estimates_schema", "occur twice")
        self.assertFails(result, "estimate_recompute", "a combination is missing or foreign")

    def test_missing_metric_fails_coverage(self):
        estimates = [e for e in self.world.estimates if e["metric_id"] != "C05"]
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["metric_coverage"], "C05")

    def test_share_out_of_range_fails_bounds(self):
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "Q02", "BASE", "pilot")
        e["numerator"] = e["denominator"] + 1
        e["value"] = float(e["numerator"]) / e["denominator"]
        self.assertFails(self.world.validate(estimates=estimates), "estimate_bounds", "out of range")

    def test_one_numerator_contradicting_the_data_fails_recompute(self):
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "Q06", "BASE", "pilot")
        e["numerator"] -= 1
        e["value"] = float(e["numerator"]) / e["denominator"]
        result = self.world.validate(estimates=estimates)
        self.assertFails(result, "estimate_recompute", "Q06 BASE pilot")
        self.assertFails(result, "block_additivity", "Q06")

    def test_missing_anchor_fails_recompute(self):
        estimates = [e for e in self.world.estimates
                     if not (e["metric_id"] == "R04" and e["block"] == "pilot"
                             and e["strata"].get("variant") == "test_feedback")]
        self.assertFails(self.world.validate(estimates=estimates), "estimate_recompute", "required estimate")

    def test_final_must_equal_step_two(self):
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "Q05", "STEP", "full_ext", variant="combined_feedback", step=2)
        e["value"] = (e["value"] or 0) * 0.5 + 0.001
        self.assertFails(self.world.validate(estimates=estimates), "final_equals_step2", "value")

    def test_transition_matrix_must_sum_to_the_cohort(self):
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "R01", "FINAL", "full_ext", endpoint="Q06", variant="test_feedback",
                 transition="pass->pass")
        e["numerator"] += 1
        e["value"] = float(e["numerator"]) / e["denominator"]
        self.assertFails(self.world.validate(estimates=estimates), "distribution_sums", "numerators sum")
        estimates = copy.deepcopy(self.world.estimates)
        for e in estimates:
            if e["metric_id"] == "R01" and e["block"] == "pilot" and e["strata"]["variant"] == "static_feedback":
                e["denominator"] += 1
                e["value"] = float(e["numerator"]) / e["denominator"]
        self.assertFails(self.world.validate(estimates=estimates), "distribution_sums", "cohort")

    def test_composite_must_be_the_sum_of_the_blocks(self):
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "C01", "REPAIR_CANDIDATES", core.COMPOSITE, variant="static_feedback",
                 quantity="records_per_trajectory")
        e["numerator"] += 1
        e["value"] = float(e["numerator"]) / e["denominator"]
        # C01 is recomputed from the generations and trajectories as well
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["block_additivity", "estimate_recompute"],
                             "C01")

    def test_primary_family_needs_twelve_holm_adjusted_hypotheses(self):
        estimates = copy.deepcopy(self.world.estimates)
        primary = [e for e in estimates if e["p_value"] is not None]
        self.assertEqual(len(primary), 12)
        primary[0]["p_holm"] = min(1.0, primary[0]["p_holm"] + 0.01)
        rerun = [copy.deepcopy(e) for e in estimates if e["p_value"] is not None]
        self.assertOnlyFails(self.world.validate(estimates=estimates, estimates_rerun=rerun), ["primary_family"],
                             "Holm p")
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "R02", "FINAL", "pilot", endpoint="Q06", variant="static_feedback")
        e["p_value"], e["p_holm"], e["reject_holm"] = 0.5, 0.5, False
        self.assertFails(self.world.validate(estimates=estimates), "primary_family", "outside the primary family")
        estimates = [e for e in copy.deepcopy(self.world.estimates)
                     if not (e["p_value"] is not None and e["metric_id"] == "R05")]
        self.assertFails(self.world.validate(estimates=estimates), "primary_family", "expected the 12 hypotheses")

    def test_holm_and_comparisons(self):
        adjusted = validate.holm_adjusted(OrderedDict([("a", 0.01), ("b", 0.04), ("c", 0.03), ("d", 0.5)]))
        self.assertAlmostEqual(adjusted["a"], 0.04)
        self.assertAlmostEqual(adjusted["c"], 0.09)
        self.assertAlmostEqual(adjusted["b"], 0.09)  # monotone: max(0.09, 2 * 0.04)
        self.assertAlmostEqual(adjusted["d"], 0.5)
        self.assertEqual(validate.comparison_variants("static_feedback-test_feedback"),
                         ("static_feedback", "test_feedback"))
        self.assertEqual(validate.comparison_variants("combined vs static"), ("combined_feedback", "static_feedback"))
        self.assertIsNone(validate.comparison_variants("G01-E05(BASE)"))

    def test_recompute_matches_hand_counts(self):
        index = validate.Index(self.world.dataset)
        engine = validate.Recompute(index)
        base = [a for a in self.world.rows["artifacts"] if a["iteration"] == 0 and a["block"] == "pilot"]
        expected = (sum(1 for a in base if a["correctness_verdict"] == "pass"), len(base))
        self.assertEqual(engine.estimate({"metric_id": "Q06", "population": "BASE", "block": "pilot",
                                          "strata": {}}), expected)
        trajectories = [t for t in self.world.rows["trajectories"] if t["variant"] == "combined_feedback"]
        byid = OrderedDict((a["artifact_id"], a) for a in self.world.rows["artifacts"])
        passes = sum(1 for t in trajectories if byid[t["final_artifact"]]["correctness_verdict"] == "pass")
        self.assertEqual(engine.estimate({"metric_id": "Q06", "population": "FINAL", "block": core.COMPOSITE,
                                          "strata": {"variant": "combined_feedback"}}), (passes, len(trajectories)))
        net = sum((byid[t["final_artifact"]]["correctness_verdict"] == "pass")
                  - (byid[t["artifact_iter0"]]["correctness_verdict"] == "pass") for t in trajectories)
        self.assertEqual(engine.estimate({"metric_id": "R04", "population": "FINAL", "block": core.COMPOSITE,
                                          "strata": {"endpoint": "Q06", "variant": "combined_feedback"}}),
                         (net, len(trajectories)))
        valid = [a for a in self.world.rows["artifacts"] if a["iteration"] == 0 and a["enh_valid"] > 0]
        self.assertEqual(engine.estimate({"metric_id": "E02", "population": "BASE", "block": core.COMPOSITE,
                                          "strata": {}}),
                         (sum(1 for a in valid if a["enh_all_pass"] == 1), len(valid)))
        budget = sum(1 for t in self.world.rows["trajectories"] if t["variant"] == "static_feedback"
                     and t["block"] == "full_ext" and t["terminal_status"] == "stopped_budget")
        self.assertEqual(engine.estimate({"metric_id": "R07", "population": "TRAJECTORIES", "block": "full_ext",
                                          "strata": {"variant": "static_feedback"}}), (budget, 6))
        with self.assertRaises(validate.NotRecomputable):
            engine.estimate({"metric_id": "F05", "population": "BASE", "block": "pilot", "strata": {"tool": "x"}})

    # -- regressions of the review findings (bootstrap settings, recomputation, labels, ledgers) ------------
    def test_exploratory_or_short_bootstraps_fail(self):
        estimates = copy.deepcopy(self.world.estimates)
        for e in estimates:
            if e["p_value"] is not None:
                e["replicates"] = 50
                e["note"] = "EXPLORATORY: 50 bootstrap replicates (methodology 10000), not confirmatory"
        e = find(estimates, "Q06", "BASE", core.COMPOSITE)
        e["ci_method"], e["replicates"] = validate.CI_METHOD, 20
        e["ci_low"], e["ci_high"] = max(0.0, e["value"] - 0.1), min(1.0, e["value"] + 0.1)
        rerun = [copy.deepcopy(x) for x in estimates if x["p_value"] is not None]
        result = self.world.validate(estimates=estimates, estimates_rerun=rerun)
        self.assertOnlyFails(result, ["estimates_schema", "primary_family"])
        schema = json.dumps(check(result, "estimates_schema")["detail"])
        self.assertIn("EXPLORATORY", schema)
        self.assertIn("20 bootstrap replicates (+ 0 skipped), the methodology fixes 2000", schema)
        self.assertIn("the methodology fixes 10000 (primary family)", json.dumps(check(result, "primary_family")["detail"]))
        # skipped replicates documented in the note are part of the accounting
        estimates = copy.deepcopy(self.world.estimates)
        primary = [e for e in estimates if e["p_value"] is not None]
        primary[0]["replicates"] = 9990
        primary[0]["note"] = "10 of 10000 bootstrap replicates skipped (denominator 0)"
        primary[1]["replicates"] = 9990
        rerun = [copy.deepcopy(x) for x in estimates if x["p_value"] is not None]
        result = self.world.validate(estimates=estimates, estimates_rerun=rerun)
        self.assertOnlyFails(result, ["estimates_schema", "primary_family"], "9990 bootstrap replicates (+ 0 skipped)")
        self.assertNotIn("10 skipped", json.dumps(check(result, "primary_family")["detail"]))

    def test_foreign_labels_fail_instead_of_being_skipped(self):
        src = find(self.world.estimates, "Q06", "FINAL", "pilot", variant="static_feedback")
        cases = [({"variant": "static"}, None, "variant 'static'"),
                 ({}, "FINALS", "outside the methodology's populations"),
                 ({"step": 1}, None, "with a step stratum"),
                 ({"model_id": "not_a_model"}, None, None)]
        for strata, population, schema_fragment in cases:
            estimates = copy.deepcopy(self.world.estimates)
            bad = copy.deepcopy(src)
            bad["strata"].update(strata)
            bad["population"] = population or bad["population"]
            bad["numerator"], bad["value"] = 0, 0.0
            estimates.append(bad)
            result = self.world.validate(estimates=estimates)
            self.assertFails(result, "estimate_recompute", "not recomputable")
            if schema_fragment:
                self.assertFails(result, "estimates_schema", schema_fragment)
        self.assertEqual(validate.strata_value_problems("S01", {"tool": "tsan", "state": "PARTIAL", "step": 2}), [])
        self.assertEqual(len(validate.strata_value_problems("F01", {"state": "PARTIAL", "iteration": 3})), 2)

    def test_r01_f05_f06_and_effort_estimates_are_recomputed(self):
        def failing_recompute(mutate, fragment):
            estimates = copy.deepcopy(self.world.estimates)
            mutate(estimates)
            self.assertFails(self.world.validate(estimates=estimates), "estimate_recompute", fragment)

        def swap(estimates):
            swapped = 0
            for block in core.BLOCKS + (core.COMPOSITE,):
                for variant in core.VARIANTS:
                    a = find(estimates, "R01", "FINAL", block, endpoint="Q06", variant=variant,
                             transition="pass->not_pass")
                    b = find(estimates, "R01", "FINAL", block, endpoint="Q06", variant=variant,
                             transition="not_pass->pass")
                    swapped += a["numerator"] != b["numerator"]
                    for field in ("numerator", "value"):
                        a[field], b[field] = b[field], a[field]
            self.assertGreater(swapped, 0)
        failing_recompute(swap, "R01 FINAL")

        def f05(estimates):
            for block in ("pilot", core.COMPOSITE):
                find(estimates, "F05", "BASE", block, tool="compiler", family="build", kind="reported_blocking",
                     quantity="findings")["numerator"] += 7
        failing_recompute(f05, "F05 BASE")

        def f06(estimates):
            find(estimates, "F06", "GENERATED", core.COMPOSITE, pair="tsan+llov", **{"class": "race"})["n10"] += 1
        failing_recompute(f06, "n10")

        def c02(estimates):
            find(estimates, "C02", "BASE", "pilot", quantity="output_tokens")["numerator"] += 1
        failing_recompute(c02, "C02 BASE")

        def c04(estimates):
            find(estimates, "C04", "GENERATED", "full_ext", tool="compiler", outlier_rule="all")["p95"] = 99.0
        failing_recompute(c04, "p95")

        def c05(estimates):
            e = find(estimates, "C05", "FINAL", core.COMPOSITE, variant="static_feedback", quantity="per_100_requests")
            e["value"] = (e["value"] or 0) + 1.0
        failing_recompute(c05, "C05 FINAL")

        def g01(estimates):
            find(estimates, "G01", "FINAL", "pilot", variant="test_feedback",
                 comparison="G01-E05(BASE)")["reference_denominator"] += 1
        failing_recompute(g01, "reference_denominator")

        def drop_f05(estimates):
            counts = [e for e in estimates if (e["metric_id"], e["population"], e["block"]) == ("F05", "GENERATED",
                                                                                              "full_ext")
                      and e["strata"]["quantity"] == "findings"]
            largest = max(counts, key=lambda e: e["numerator"])
            self.assertGreater(largest["numerator"], 0)
            estimates.remove(largest)
        failing_recompute(drop_f05, "a combination is missing")

        def drop_f06(estimates):
            estimates.remove(find(estimates, "F06", "GENERATED", "pilot", pair="must+parcoach",
                                  **{"class": "mpi_usage+deadlock"}))
        failing_recompute(drop_f06, "no agreement estimate")

        def drop_r01(estimates):
            estimates.remove(find(estimates, "R01", "FINAL", "pilot", endpoint="F02", variant="test_feedback",
                                  transition="DIRTY->DIRTY"))
        failing_recompute(drop_r01, "required estimate")

    def test_generated_per_iteration_distributions_are_exact(self):
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "Q08", "GENERATED", "pilot", iteration=1, verdict="pass")
        e["numerator"] += 1
        e["value"] = float(e["numerator"]) / e["denominator"]
        result = self.world.validate(estimates=estimates)
        self.assertFails(result, "distribution_sums", "numerators sum to")
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "R06", "TRAJECTORIES", "full_ext", variant="combined_feedback", status="stopped_budget",
                 iteration=2)
        e["numerator"] += 1
        e["value"] = float(e["numerator"]) / e["denominator"]
        self.assertFails(self.world.validate(estimates=estimates), "distribution_sums", "numerators sum to")

    def test_ledger_identity_and_loop_kind(self):
        def rewrite(relative, change):
            path = self.world.root / relative
            original = path.read_text(encoding="utf-8")
            if relative.endswith(".jsonl"):
                rows = [json.loads(line) for line in original.splitlines() if line.strip()]
                change(rows)
                path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            else:
                document = json.loads(original, object_pairs_hook=OrderedDict)
                change(document)
                path.write_text(json.dumps(document), encoding="utf-8")
            return path, original

        origin = "thesis/results/intermediate/%s/%s/repair/static_feedback/state.jsonl" % (ORIGIN, MODELS2[1])

        def foreign_rows(rows):
            rows[0]["run_id"] = "some_foreign_run"
            rows[0]["model_id"] = "another_model"
        path, original = rewrite(origin, foreign_rows)
        self.assertOnlyFails(self.world.validate(), ["trajectories_ledger"], "foreign %s state row" % ORIGIN)
        path.write_text(original, encoding="utf-8")
        owner = loop_owner("full_ext", MODELS2[0], "static_feedback")[0]
        wave = "thesis/results/intermediate/%s/%s/repair/static_feedback/wave_state.json" % (owner, MODELS2[0])
        path, original = rewrite(wave, lambda document: document.update(model_id=MODELS2[1]))
        self.assertOnlyFails(self.world.validate(), ["trajectories_ledger"], "foreign wave state")
        path.write_text(original, encoding="utf-8")
        census = copy.deepcopy(self.world.census_result)
        loop = [l for l in census["loops"] if l["kind"] == "native"][0]
        loop["kind"] = "continued"
        self.assertOnlyFails(self.world.validate(census_result=census), ["trajectories_ledger"], "census kind")
        trajectory = [t for t in self.world.rows["trajectories"] if t["loop_kind"] == "native"][0]
        trajectory["loop_kind"] = "continued"
        self.assertOnlyFails(self.world.validate(), ["trajectories_ledger"], "loop_kind")

    def test_new_metric_families_match_hand_counts(self):
        index = validate.Index(self.world.dataset)
        engine = validate.Recompute(index)
        rows = self.world.rows
        byid = OrderedDict((a["artifact_id"], a) for a in rows["artifacts"])

        def facts(metric, population, block, **strata):
            return engine.expected({"metric_id": metric, "population": population, "block": block, "strata": strata})
        combined = [t for t in rows["trajectories"] if t["variant"] == "combined_feedback"]
        improved = sum(1 for t in combined if byid[t["artifact_iter0"]]["correctness_verdict"] != "pass"
                       and byid[t["final_artifact"]]["correctness_verdict"] == "pass")
        r01 = facts("R01", "FINAL", core.COMPOSITE, endpoint="Q06", variant="combined_feedback",
                    transition="not_pass->pass")
        self.assertEqual((r01["numerator"], r01["denominator"]), (improved, len(combined)))
        pilot_base = [a for a in rows["artifacts"] if a["block"] == "pilot" and a["iteration"] == 0]
        ids = set(a["artifact_id"] for a in pilot_base)
        compiler = [f for f in rows["findings"] if f["artifact_id"] in ids and f["tool"] == "compiler"]
        f05 = facts("F05", "BASE", "pilot", tool="compiler", family="build", kind="reported_blocking",
                    quantity="findings")
        self.assertEqual((f05["numerator"], f05["denominator"]), (len(compiler), None))
        f05 = facts("F05", "BASE", "pilot", tool="compiler", family="build", kind="reported_blocking",
                    quantity="artifacts_with_finding")
        self.assertEqual((f05["numerator"], f05["denominator"]),
                         (len(set(f["artifact_id"] for f in compiler)), len(pilot_base)))
        entries = OrderedDict(((e["artifact_id"], e["tool"]), e) for e in rows["tool_entries"])
        both = [a for a in rows["artifacts"] if a["execution_model"] == "omp"
                and all(entries[(a["artifact_id"], t)]["state"] == "COMPLETED" for t in ("tsan", "llov"))]
        race = set(f["artifact_id"] for f in rows["findings"] if f["tool"] == "tsan" and f["family"] == "race"
                   and f["kind"] == "reported_blocking")
        n10 = sum(1 for a in both if a["artifact_id"] in race)
        f06 = facts("F06", "GENERATED", core.COMPOSITE, pair="tsan+llov", **{"class": "race"})
        self.assertGreater(n10, 0)
        self.assertEqual((f06["n11"], f06["n10"], f06["n01"], f06["n00"]), (0, n10, 0, len(both) - n10))
        self.assertEqual(f06["positive_agreement"], 0.0)
        candidates = [a for a in rows["artifacts"] if a["block"] == "full_ext" and a["variant"] == "static_feedback"]
        c01 = facts("C01", "REPAIR_CANDIDATES", "full_ext", variant="static_feedback", quantity="records_per_trajectory")
        self.assertEqual((c01["numerator"], c01["denominator"]), (len(candidates), 6))
        test = [a for a in rows["artifacts"] if a["variant"] == "test_feedback"]
        reported = [a for a in test if a["model_id"] == MODELS2[0]]
        c02 = facts("C02", "REPAIR_CANDIDATES", core.COMPOSITE, variant="test_feedback", quantity="reasoning_tokens")
        self.assertEqual((c02["numerator"], c02["denominator"], c02["generations"]),
                         (10 * len(reported), len(reported), len(test)))
        static = [t for t in rows["trajectories"] if t["variant"] == "static_feedback"]
        gain = sum(1 for t in static if byid[t["artifact_iter0"]]["correctness_verdict"] != "pass"
                   and byid[t["final_artifact"]]["correctness_verdict"] == "pass")
        tokens = 50 * sum(1 for a in rows["artifacts"] if a["variant"] == "static_feedback")
        c05 = facts("C05", "FINAL", core.COMPOSITE, variant="static_feedback", quantity="per_1M_output_tokens")
        self.assertEqual((c05["numerator"], c05["denominator"]), (gain, tokens))
        self.assertAlmostEqual(c05["value"], gain * 1e6 / tokens)
        c04 = facts("C04", "GENERATED", core.COMPOSITE, tool="compiler", outlier_rule="all")
        self.assertEqual((c04["value"], c04["p95"], c04["n"], c04["timeouts"]), (1.5, 1.5, len(rows["artifacts"]), 0))
        rate = facts("G01", "FINAL", "pilot", variant="static_feedback")
        reference = facts("E05", "BASE", "pilot")
        g01 = facts("G01", "FINAL", "pilot", variant="static_feedback", comparison="G01-E05(BASE)")
        self.assertEqual((g01["reference_numerator"], g01["reference_denominator"]),
                         (reference["numerator"], reference["denominator"]))
        if rate["value"] is not None and reference["value"] is not None:
            self.assertAlmostEqual(g01["value"], rate["value"] - reference["value"])
        with self.assertRaises(validate.NotRecomputable):
            facts("F06", "GENERATED", "pilot", pair="tsan+memcheck", **{"class": "race"})
        with self.assertRaises(validate.NotRecomputable):
            facts("C05", "FINAL", "pilot", variant="static_feedback", quantity="per_1000_requests")

    def test_manifest_must_describe_this_dataset(self):
        root = self.world.root
        with mock.patch.object(core, "git_state", lambda root: git_state()):
            start = manifest.input_manifest(root, None)
        # the start manifest (built before the normalizer ran) cannot stand in for the end manifest
        self.assertOnlyFails(self.world.validate(manifest=start), ["input_stability"], "lists no input file")
        self.assertEqual(check(self.world.validate(manifest_start=start), "input_stability")["status"], "PASS")
        relative = list(self.world.dataset.provenance["files_read"])[0]
        write(root, relative, "{\"changed\": 1}\n")
        self.assertOnlyFails(self.world.validate(manifest=start), ["input_stability"], "dataset_inputs")
        write(root, relative, "{}\n")
        # the manifest of another dataset (other counts, another recorded sha)
        other = core.Dataset(copy.deepcopy(self.world.dataset.tables), copy.deepcopy(self.world.dataset.provenance))
        other.tables["findings"].pop()
        other.provenance["files_read"][relative] = "0" * 64
        with mock.patch.object(core, "git_state", lambda root: git_state()):
            foreign = manifest.input_manifest(root, other)
        result = self.world.validate(manifest=foreign)
        self.assertOnlyFails(result, ["input_stability"], "dataset_inputs.counts")
        self.assertIn("carry another sha256", json.dumps(check(result, "input_stability")["detail"]))
        # code changed between the start and the end manifest
        write(root, core.PACKAGE_REL + "/module2.py", "y = 2\n")
        self.world.refresh_manifest()
        self.assertOnlyFails(self.world.validate(manifest_start=start), ["input_stability"],
                             "package_sources differs between the start and the end manifest")
        with mock.patch.object(core, "git_state", lambda root: git_state()):
            start = manifest.input_manifest(root, None)
        # write mode: clean tree at the preflight HEAD, both manifests required
        self.assertEqual(check(self.world.validate(manifest_start=start, write_mode=True, preflight_head=HEAD),
                               "input_stability")["status"], "PASS")
        self.assertOnlyFails(self.world.validate(write_mode=True, preflight_head=HEAD), ["input_stability"],
                             "needs the start manifest")
        self.assertOnlyFails(self.world.validate(manifest_start=start, write_mode=True), ["input_stability"],
                             "needs the HEAD")
        self.assertOnlyFails(self.world.validate(manifest_start=start, write_mode=True, preflight_head="b" * 40),
                             ["input_stability"], "is not the preflight HEAD")
        with mock.patch.object(core, "git_state", lambda root: git_state(clean=False)):
            dirty = manifest.input_manifest(root, self.world.dataset)
        self.assertEqual(check(self.world.validate(manifest=dirty), "input_stability")["status"], "PASS")
        self.assertOnlyFails(self.world.validate(manifest=dirty, manifest_start=start, write_mode=True,
                                                 preflight_head=HEAD), ["input_stability"], "dirty worktree")

    # -- rendering, stability, reproducibility ---------------------------------------------------------
    def test_percentage_without_denominator_fails_tables(self):
        tables = copy.deepcopy(self.world.tables)
        tables[0]["rows"][0]["n"] = "3"
        self.assertOnlyFails(self.world.validate(tables=tables), ["tables"], "without an n/N")
        tables = copy.deepcopy(self.world.tables)
        tables[0]["population"] = ""
        self.assertFails(self.world.validate(tables=tables), "tables", "names no population")

    def test_structured_ratio_cells_need_their_denominator(self):
        tables = copy.deepcopy(self.world.tables)
        tables[1]["rows"][0]["q06"]["denominator"] = None
        self.assertOnlyFails(self.world.validate(tables=tables), ["tables"], "positive denominator")
        tables = copy.deepcopy(self.world.tables)
        tables[1]["rows"][0]["gain"]["value"] = -0.2
        self.assertFails(self.world.validate(tables=tables), "tables", "!=")
        tables = copy.deepcopy(self.world.tables)
        tables[1]["rows"][0]["q06"] = 0.5
        self.assertFails(self.world.validate(tables=tables), "tables", "without numerator/denominator")
        tables = copy.deepcopy(self.world.tables)
        tables[1]["rows"][0]["ci"] = OrderedDict([("ci_low", 0.9), ("ci_high", 0.1)])
        self.assertFails(self.world.validate(tables=tables), "tables", "inverted")
        tables = copy.deepcopy(self.world.tables)
        del tables[1]["rows"][1]["n"]
        self.assertFails(self.world.validate(tables=tables), "tables", "does not match the columns")

    def test_figure_rows_must_match_columns(self):
        figures = copy.deepcopy(self.world.figures)
        figures[0]["data_rows"].append(OrderedDict([("x", 3)]))
        self.assertOnlyFails(self.world.validate(figures=figures), ["figures"], "data row")

    def test_changed_input_fails_stability(self):
        relative = list(self.world.dataset.provenance["files_read"])[0]
        write(self.world.root, relative, "{\"changed\": 1}\n")
        self.assertOnlyFails(self.world.validate(), ["input_stability"], relative)
        tampered = copy.deepcopy(self.world.manifest)
        tampered["totals"]["files"] += 1
        self.assertFails(self.world.validate(manifest=tampered), "input_stability", "reproduce its hash")

    def test_rerun_must_reproduce_the_primary_family(self):
        rerun = copy.deepcopy(self.world.rerun)
        rerun[0]["ci_low"] = rerun[0]["ci_low"] - 0.01
        self.assertOnlyFails(self.world.validate(estimates_rerun=rerun), ["reproducibility"], "ci_low")
        self.assertOnlyFails(self.world.validate(estimates_rerun=None), ["reproducibility"], "not provided")

    # -- the post-freeze addendum and the DESIGN2 contract keys (round 2) ------------------------------
    def test_addendum_metrics_match_hand_counts(self):
        rows = self.world.rows
        byid = OrderedDict((a["artifact_id"], a) for a in rows["artifacts"])
        traj = OrderedDict(((t["cell_id"], t["variant"]), t) for t in rows["trajectories"])
        cells = [c["cell_id"] for c in rows["base_cells"]]
        entries = OrderedDict(((e["artifact_id"], e["stage"], e["tool"]), e) for e in rows["tool_entries"])
        engine = validate.Recompute(validate.Index(self.world.dataset))

        def facts(metric, population, block, **strata):
            return engine.expected({"metric_id": metric, "population": population, "block": block, "strata": strata})

        def final(cell, variant):
            return byid[traj[(cell, variant)]["final_artifact"]]

        def q06(a):
            return int(a["correctness_verdict"] == "pass")     # the world has no baseline_incompatible verdict
        # X01: cells with an auto-closed artifact on any trajectory leave the paired cohort
        closed = set(t["cell_id"] for t in rows["trajectories"] for k in range(t["final_iteration"] + 1)
                     if byid[t["artifact_iter%d" % k]]["clean_auto_closed"])
        self.assertTrue(0 < len(closed) < len(cells))
        kept = [c for c in cells if c not in closed]
        base = OrderedDict((c, byid[traj[(c, "static_feedback")]["artifact_iter0"]]) for c in cells)
        x01 = facts("X01", "FINAL", core.COMPOSITE, endpoint="Q06", variant="static_feedback")
        self.assertEqual((x01["numerator"], x01["denominator"], x01["excluded"]),
                         (sum(q06(final(c, "static_feedback")) - q06(base[c]) for c in kept), len(kept), len(closed)))
        x01 = facts("X01", "FINAL", "pilot", endpoint="Q06", comparison="test_feedback-combined_feedback")
        pilot_kept = [c for c in kept if c.startswith("pilot|")]
        self.assertEqual((x01["numerator"], x01["denominator"]),
                         (sum(q06(final(c, "test_feedback")) - q06(final(c, "combined_feedback")) for c in pilot_kept),
                          len(pilot_kept)))
        r04 = facts("R04", "FINAL", core.COMPOSITE, endpoint="Q06", variant="static_feedback")
        self.assertEqual(r04["denominator"], len(cells))       # the frozen R04 keeps the auto-closed cells

        # X02: findings of entries in a gap state no longer make an artifact DIRTY
        def static(a):
            return [e for (aid, stage, tool), e in entries.items() if aid == a["artifact_id"] and stage == "static"
                    and tool in core.STATIC_ANALYSIS_TOOLS and e["applicable"]]
        bases = [a for a in rows["artifacts"] if a["iteration"] == 0]
        x02_dirty = [a for a in bases if any(e["num_reported_blocking"] and e["state"] in ("COMPLETED", "PARTIAL")
                                             for e in static(a))]
        frozen_only = [a for a in bases if a["static_three_state"] == "DIRTY" and a not in x02_dirty]
        self.assertGreater(len(frozen_only), 0)
        x02 = facts("X02", "BASE", core.COMPOSITE, state="DIRTY")
        self.assertEqual((x02["numerator"], x02["denominator"], x02["dirty_only_under_frozen_rule"]),
                         (len(x02_dirty), len(bases), len(frozen_only)))
        nfi = facts("X02", "BASE", core.COMPOSITE, state="NO_FINDING_INCOMPLETE")["numerator"]
        f01 = sum(1 for a in bases if a["static_three_state"] == "NO_FINDING_INCOMPLETE")
        self.assertEqual(nfi, f01 + len(frozen_only))           # they become NO_FINDING_INCOMPLETE
        # X03: DIRTY only via one tool; the top check ids by composite BASE reported blocking findings
        dirty = [a for a in bases if a["static_three_state"] == "DIRTY"]
        via = [a for a in dirty if set(e["tool"] for e in static(a) if e["num_reported_blocking"]) == {"clang_tidy"}]
        x03 = facts("X03", "BASE", core.COMPOSITE, tool="clang_tidy", quantity="dirty_only_via_tool")
        self.assertEqual((x03["numerator"], x03["denominator"]), (len(via), len(dirty)))
        ids = set(a["artifact_id"] for a in bases)
        counted = Counter(f["check_id"] for f in rows["findings"] if f["artifact_id"] in ids and f["tool"] == "clang_tidy"
                          and f["kind"] == "reported_blocking")
        self.assertEqual(list(engine.x03_top()["clang_tidy"]),
                         [c for c, _ in sorted(counted.items(), key=lambda item: (-item[1], item[0]))])
        self.assertEqual(engine.x03_top()["llov"], ())           # no blocking finding: no check id rows
        check_id = engine.x03_top()["clang_tidy"][0]
        x03 = facts("X03", "BASE", "pilot", tool="clang_tidy", check_id=check_id, quantity="blocking_findings")
        pilot = set(a["artifact_id"] for a in bases if a["block"] == "pilot")
        self.assertEqual((x03["numerator"], x03["denominator"], x03["value"]),
                         (sum(1 for f in rows["findings"] if f["artifact_id"] in pilot and f["tool"] == "clang_tidy"
                              and f["check_id"] == check_id and f["kind"] == "reported_blocking"), None, None))
        x03 = facts("X03", "BASE", "pilot", tool="clang_tidy", check_id=check_id, quantity="artifacts_with_check")
        with_check = set(f["artifact_id"] for f in rows["findings"] if f["artifact_id"] in pilot
                         and f["tool"] == "clang_tidy" and f["check_id"] == check_id and f["kind"] == "reported_blocking")
        self.assertEqual((x03["numerator"], x03["denominator"]), (len(with_check), len(pilot)))
        # X04: static verdict among the failing FINAL artifacts
        finals = [final(c, "static_feedback") for c in cells]
        failing = [a for a in finals if a["correctness_verdict"] not in ("pass", "baseline_incompatible")]
        x04 = facts("X04", "FINAL", core.COMPOSITE, variant="static_feedback", state="CLEAN_COMPLETE")
        self.assertEqual((x04["numerator"], x04["denominator"]),
                         (sum(1 for a in failing if a["static_three_state"] == "CLEAN_COMPLETE"), len(failing)))
        # X05: final iteration of the trajectories with the loop's own clean stop
        stopped = [t for t in rows["trajectories"] if t["variant"] == "test_feedback"
                   and t["terminal_status"] in ("stopped_clean", "stopped_tests_pass")]
        x05 = facts("X05", "TRAJECTORIES", core.COMPOSITE, variant="test_feedback")
        self.assertEqual((x05["numerator"], x05["denominator"]),
                         (sum(t["final_iteration"] for t in stopped), len(stopped)))
        self.assertGreater(x05["numerator"], 0)
        x05 = facts("X05", "TRAJECTORIES", core.COMPOSITE, variant="test_feedback", iteration=1)
        self.assertEqual(x05["numerator"], sum(1 for t in stopped if t["final_iteration"] == 1))

        # X06: the joint Q06 x E02 transition of the same cell
        def e02(a):
            return int(a["enh_all_pass"] == 1)
        joint = Counter()
        for c in cells:
            b, f = base[c], final(c, "combined_feedback")
            joint[("%s->%s" % (("pass", "not_pass")[1 - q06(b)], ("pass", "not_pass")[1 - q06(f)]),
                   "%s->%s" % (("all_pass", "not_all_pass")[1 - e02(b)], ("all_pass", "not_all_pass")[1 - e02(f)]))] += 1
        total = 0
        for q in engine.r01_labels("Q06"):
            for heldout in engine.r01_labels("E02"):
                x06 = facts("X06", "FINAL", core.COMPOSITE, variant="combined_feedback", transition=q,
                            heldout_transition=heldout)
                self.assertEqual((x06["numerator"], x06["denominator"]), (joint[(q, heldout)], len(cells)))
                total += x06["numerator"]
        self.assertEqual(total, len(cells))
        with self.assertRaises(validate.NotRecomputable):
            facts("X06", "FINAL", "pilot", variant="combined_feedback", transition="pass->pass",
                  heldout_transition="pass->pass")
        with self.assertRaises(validate.NotRecomputable):
            facts("X02", "BASE", "pilot", model_id=MODELS2[0], state="DIRTY")

    def test_x01_cohort_tampering_fails(self):
        # one more auto-closed candidate (cleaning flags consistent) moves a cell out of the X01 cohort
        rows = self.world.rows
        byid = OrderedDict((a["artifact_id"], a) for a in rows["artifacts"])
        engine = validate.Recompute(validate.Index(self.world.dataset))
        closed = engine.auto_closed_cells()
        trajectory = [t for t in rows["trajectories"] if t["final_iteration"] >= 1 and t["cell_id"] not in closed][0]
        candidate = byid[trajectory["artifact_iter1"]]
        candidate.update(clean_auto_closed=True, clean_any=True, clean_any_including_fence=True)
        self.assertOnlyFails(self.world.validate(), ["estimate_recompute"], "X01")
        candidate.update(clean_auto_closed=False)
        candidate.update(clean_any=any(candidate[c] for c in core.SCHEMAS["artifacts"] if c.startswith("clean_")
                                       and c not in ("clean_any", "clean_any_including_fence", "clean_used_fence")),
                         clean_any_including_fence=any(candidate[c] for c in core.SCHEMAS["artifacts"]
                                                       if c.startswith("clean_")
                                                       and c not in ("clean_any", "clean_any_including_fence")))
        self.assertEqual(self.world.validate()["status"], "PASS")
        # an X01 estimate on the frozen R04 cohort (the auto-closed rule ignored) fails
        estimates = copy.deepcopy(self.world.estimates)
        x01 = find(estimates, "X01", "FINAL", "full_ext", endpoint="Q06", variant="test_feedback")
        r04 = find(estimates, "R04", "FINAL", "full_ext", endpoint="Q06", variant="test_feedback")
        self.assertNotEqual(x01["denominator"], r04["denominator"])
        x01.update(numerator=r04["numerator"], denominator=r04["denominator"], value=r04["value"], excluded=0)
        self.assertFails(self.world.validate(estimates=estimates), "estimate_recompute", "X01 FINAL full_ext")
        # a missing excluded count fails
        estimates = copy.deepcopy(self.world.estimates)
        del find(estimates, "X01", "FINAL", "pilot", endpoint="E02", comparison="static_feedback-test_feedback")["excluded"]
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimate_recompute"], "lacks excluded")

    def test_x01_excluded_admits_one_reading_for_all_estimates(self):
        rows = copy.deepcopy(self.world.rows)
        byid = OrderedDict((a["artifact_id"], a) for a in rows["artifacts"])
        engine = validate.Recompute(validate.Index(core.Dataset(rows)))
        closed = engine.auto_closed_cells()
        trajectory = [t for t in rows["trajectories"] if t["final_iteration"] >= 1 and t["cell_id"] not in closed][0]
        byid[trajectory["artifact_iter1"]]["correctness_verdict"] = "baseline_incompatible"   # leaves the Q06 cohort
        dataset = core.Dataset(rows)
        index = validate.Index(dataset)
        estimates = make_estimates(dataset)
        methodology = self.world.methodology
        problems, facts = validate.recompute_problems(estimates, index, methodology)
        self.assertEqual(problems, [])
        self.assertEqual(facts["readings"]["X01.excluded"], [validate.X01_READINGS[0]])   # the readings differ here
        engine = validate.Recompute(index)
        for e in estimates:      # reading b everywhere: auto-closed removals + the endpoint's own exclusions
            if e["metric_id"] == "X01":
                e["excluded"] = engine.block_cells(e["block"]) - e["denominator"]
        problems, facts = validate.recompute_problems(estimates, index, methodology)
        self.assertEqual(problems, [])
        self.assertEqual(facts["readings"]["X01.excluded"], [validate.X01_READINGS[1]])
        q06 = find(estimates, "X01", "FINAL", trajectory["block"], endpoint="Q06", variant="static_feedback")
        q06["excluded"] -= 1     # this one follows reading a: a mixture fails
        problems = validate.recompute_problems(estimates, index, methodology)[0]
        self.assertEqual(len(problems), 1)
        self.assertIn("no single reading fits all", problems[0])
        q06["excluded"] += 7     # neither reading
        problems = validate.recompute_problems(estimates, index, methodology)[0]
        self.assertTrue(any("under the readings" in p for p in problems))

    def test_contract_keys_are_part_of_every_estimate(self):
        estimates = copy.deepcopy(self.world.estimates)
        for key in validate.CONTRACT_KEYS:
            del find(estimates, "Q05", "BASE", "pilot")[key]
        self.assertFails(self.world.validate(estimates=estimates), "estimates_schema", "lacks ['post_freeze'")
        # post_freeze true exactly for the addendum metrics, whose notes carry the POST-FREEZE prefix
        estimates = copy.deepcopy(self.world.estimates)
        find(estimates, "Q06", "BASE", core.COMPOSITE)["post_freeze"] = True
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimates_schema"],
                             "post_freeze True on a frozen metric")
        estimates = copy.deepcopy(self.world.estimates)
        find(estimates, "X04", "BASE", "pilot", state="CLEAN_COMPLETE")["post_freeze"] = False
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimates_schema"],
                             "post_freeze False on a post-freeze addendum metric")
        estimates = copy.deepcopy(self.world.estimates)
        find(estimates, "X04", "BASE", "pilot", state="CLEAN_COMPLETE")["post_freeze"] = 1
        self.assertFails(self.world.validate(estimates=estimates), "estimates_schema", "is not a boolean")
        estimates = copy.deepcopy(self.world.estimates)
        find(estimates, "X05", "TRAJECTORIES", "pilot", variant="static_feedback")["note"] = "descriptive"
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimates_schema"],
                             "POST-FREEZE addendum_1 (descriptive): ")

    def test_ci_degenerate_follows_the_bounds(self):
        def with_interval(low, high, degenerate, note=None):
            estimates = copy.deepcopy(self.world.estimates)
            e = find(estimates, "Q06", "BASE", core.COMPOSITE)
            e.update(ci_method=validate.CI_METHOD, replicates=2000, ci_low=low, ci_high=high, ci_degenerate=degenerate,
                     note=note)
            return self.world.validate(estimates=estimates)
        self.assertEqual(with_interval(0.25, 0.75, False)["status"], "PASS")
        self.assertOnlyFails(with_interval(0.5, 0.5, False), ["estimates_schema"], "contradicts the interval")
        self.assertOnlyFails(with_interval(0.25, 0.75, True), ["estimates_schema"], "contradicts the interval")
        self.assertOnlyFails(with_interval(0.5, 0.5, None), ["estimates_schema"], "contradicts the interval")
        self.assertOnlyFails(with_interval(0.5, 0.5, True), ["estimates_schema"], validate.DEGENERATE_NOTE)
        self.assertEqual(with_interval(0.5, 0.5, True, "x; " + validate.DEGENERATE_NOTE)["status"], "PASS")
        estimates = copy.deepcopy(self.world.estimates)
        find(estimates, "Q06", "BASE", core.COMPOSITE)["ci_degenerate"] = False
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimates_schema"], "without an interval")

    def test_p_resolution_fields(self):
        primary = [e for e in self.world.estimates if e["p_value"] is not None]
        self.assertEqual(set(e["p_holm_resolution"] for e in primary), {0.0024})
        rule = validate.holm_resolutions(primary, self.world.methodology)
        self.assertTrue(all(abs(r - 0.0024) < 1e-15 for _, r in rule))
        # the running maximum over the Holm order for unequal resolutions (hand values, m = 3)
        self.assertEqual([round((3 - rank + 1) * 0.0002, 10) for rank in (1, 2, 3)], [0.0006, 0.0004, 0.0002])

        def tampered(change, field="p_holm_resolution"):
            estimates = copy.deepcopy(self.world.estimates)
            change([e for e in estimates if e["p_value"] is not None])
            rerun = [copy.deepcopy(e) for e in estimates if e["p_value"] is not None]
            return self.world.validate(estimates=estimates, estimates_rerun=rerun)
        # the old rendering: the raw resolution 2/B also for the Holm-adjusted p
        self.assertOnlyFails(tampered(lambda p: p[3].update(p_holm_resolution=0.0002)), ["primary_family"],
                             "the Holm-order rule gives 0.0024")
        self.assertOnlyFails(tampered(lambda p: p[0].update(p_resolution=1.0 / 10000)), ["estimates_schema"],
                             "2 / replicates_primary")
        self.assertOnlyFails(tampered(lambda p: p[0].update(p_holm_resolution=None)), ["estimates_schema",
                                                                                         "primary_family"])
        estimates = copy.deepcopy(self.world.estimates)
        find(estimates, "R04", "FINAL", "pilot", endpoint="Q06", variant="test_feedback")["p_resolution"] = 0.0002
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimates_schema"], "outside the primary family")
        rerun = copy.deepcopy(self.world.rerun)
        rerun[0]["p_holm_resolution"] = 0.0012
        self.assertOnlyFails(self.world.validate(estimates_rerun=rerun), ["reproducibility"], "p_holm_resolution")

    def test_metric_coverage_includes_the_addendum(self):
        estimates = [e for e in self.world.estimates if e["metric_id"] != "X03"]
        result = self.world.validate(estimates=estimates)
        self.assertOnlyFails(result, ["metric_coverage", "estimate_recompute"], "X03")
        self.assertIn("required addendum estimate(s) missing", json.dumps(check(result, "estimate_recompute")))
        estimates = copy.deepcopy(self.world.estimates)
        foreign = copy.deepcopy(find(estimates, "X05", "TRAJECTORIES", "pilot", variant="static_feedback"))
        foreign["metric_id"] = "X07"
        estimates.append(foreign)
        result = self.world.validate(estimates=estimates)
        self.assertFails(result, "metric_coverage", "unknown metric ids")
        self.assertFails(result, "estimates_schema", "unknown metric id")
        self.assertEqual(check(self.world.validate(), "metric_coverage")["detail"]["metrics"],
                         len(core.all_metric_ids(self.world.methodology, self.world.addendum)))

    def test_addendum_shapes_are_complete_and_closed(self):
        estimates = copy.deepcopy(self.world.estimates)
        dropped = [e for e in estimates if e["metric_id"] == "X06" and e["block"] == "pilot" and e["numerator"] == 0][0]
        estimates.remove(dropped)
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimate_recompute"],
                             "required addendum estimate(s) missing")
        # X01 comparisons are the R05 labels of the block
        estimates = copy.deepcopy(self.world.estimates)
        extra = copy.deepcopy(find(estimates, "X01", "FINAL", "pilot", endpoint="Q06",
                                   comparison="static_feedback-test_feedback"))
        extra["strata"]["comparison"] = "test_feedback-static_feedback"
        extra.update(numerator=-extra["numerator"], value=None if extra["value"] is None else -extra["value"])
        estimates.append(extra)
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimate_recompute"], "is not an R05 label")
        # X03 check ids: the dataset's findings vocabulary (schema) and the top-N selection (recompute)
        # (nullPointer: a cppcheck blocking check of candidates only, never selected from the BASE findings)
        for tool, check_id, failing, fragment in (
                ("cppcheck", "nullPointer", ["estimate_recompute"], "not among the top 0 check ids of cppcheck"),
                ("clang_tidy", "style", ["estimates_schema", "estimate_recompute"], "occurs in no finding"),
                ("clang_tidy", "made-up-check", ["estimates_schema", "estimate_recompute"], "occurs in no finding")):
            estimates = copy.deepcopy(self.world.estimates)
            extra = copy.deepcopy(find(estimates, "X03", "BASE", "pilot", tool="clang_tidy",
                                       check_id="bugprone-narrowing-conversions", quantity="blocking_findings"))
            extra["strata"].update(tool=tool, check_id=check_id)
            estimates.append(extra)
            result = self.world.validate(estimates=estimates)
            self.assertOnlyFails(result, failing)
            self.assertFails(result, failing[0], fragment)
            self.assertFails(result, "estimate_recompute", "not recomputable")
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "X06", "FINAL", "pilot", variant="test_feedback", transition="pass->pass",
                 heldout_transition="all_pass->all_pass")
        e["strata"]["heldout_transition"] = "pass->pass"
        result = self.world.validate(estimates=estimates)
        self.assertFails(result, "estimates_schema", "heldout_transition 'pass->pass' outside its vocabulary")
        self.assertFails(result, "estimate_recompute", "not recomputable")
        self.assertEqual(validate.strata_value_problems("X03", {"tool": "cppcheck", "check_id": "", "quantity": "x"}),
                         ["check_id '' is not a non-empty string", "quantity 'x' outside its vocabulary"])

    def test_addendum_distributions_sum_to_their_cohort(self):
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "X02", "FINAL", "full_ext", variant="static_feedback", state="CLEAN_COMPLETE")
        e["numerator"] += 1
        e["value"] = float(e["numerator"]) / e["denominator"]
        result = self.world.validate(estimates=estimates)
        self.assertFails(result, "distribution_sums", "numerators sum to")
        self.assertFails(result, "estimate_recompute", "X02 FINAL full_ext")
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "X05", "TRAJECTORIES", core.COMPOSITE, variant="combined_feedback")
        e["numerator"] = 3 * e["denominator"] + 1
        e["value"] = float(e["numerator"]) / e["denominator"]
        self.assertFails(self.world.validate(estimates=estimates), "estimate_bounds", "mean numerator")
        estimates = copy.deepcopy(self.world.estimates)
        e = find(estimates, "X03", "BASE", "pilot", tool="clang_tidy", check_id="bugprone-narrowing-conversions",
                 quantity="blocking_findings")
        self.assertEqual(validate.bounds_kind(e), None)
        self.assertEqual((e["denominator"], e["value"]), (None, None))
        e = find(estimates, "X01", "FINAL", "pilot", endpoint="Q06", variant="static_feedback")
        self.assertEqual(validate.bounds_kind(e), "difference")

    def test_addendum_ci_mandate(self):
        index = validate.Index(self.world.dataset)
        block_of = OrderedDict((c["benchmark"], c["block"]) for c in self.world.rows["base_cells"])
        sizes = Counter(dict((block, 2) for block in core.BLOCKS))   # pretend two clusters per stratum
        target = 'X01 FINAL composite {"endpoint": "Q06", "variant": "static_feedback"}'
        with mock.patch.object(validate.Recompute, "clusters", lambda engine: (block_of, sizes, sizes)):
            problems = validate.recompute_problems(self.world.estimates, index, self.world.methodology)[0]
            demanded = [p for p in problems if "demands a cluster-bootstrap CI" in p]
            for fragment in (target, 'X02 BASE composite {"state": "DIRTY"}',
                             'X04 BASE composite {"state": "CLEAN_COMPLETE"}'):
                self.assertTrue(any(p.startswith(fragment) for p in demanded), fragment)
            for fragment in ('X02 BASE composite {"state": "CLEAN_COMPLETE"}', "X03 ", "X05 ", "X06 "):
                self.assertFalse(any(p.startswith(fragment) for p in demanded), fragment)
            estimates = copy.deepcopy(self.world.estimates)
            e = find(estimates, "X01", "FINAL", core.COMPOSITE, endpoint="Q06", variant="static_feedback")
            e.update(ci_method=validate.CI_METHOD, replicates=2000, ci_low=e["value"] - 0.1,
                     ci_high=e["value"] + 0.1, ci_degenerate=False)
            problems = validate.recompute_problems(estimates, index, self.world.methodology)[0]
            self.assertFalse(any(p.startswith(target) for p in problems))
        self.assertEqual(validate.addendum_ci_problems(self.world.addendum), [])
        broken = copy.deepcopy(self.world.addendum)
        broken["metrics"][4]["aggregation"] = "mean with a descriptive CI"
        self.assertIn("X05", validate.addendum_ci_problems(broken)[0])

    def test_tables_carry_bl01_and_mark_degenerate_intervals(self):
        def run(change):
            tables = copy.deepcopy(self.world.tables)
            change(tables[1])
            return self.world.validate(tables=tables)

        def cell(table):
            return table["rows"][0]["q06"]
        self.assertOnlyFails(run(lambda t: t.update(notes=[])), ["tables"], "without the BL01 note")
        # BL01 rides on footnotes as well; full_ext and SA1 cells need none
        self.assertEqual(run(lambda t: t.update(notes=[], footnotes=[OrderedDict([
            ("mark", "d"), ("text", self.world.notes["BL01"])])]))["status"], "PASS")
        self.assertEqual(run(lambda t: (t.update(notes=[]), cell(t)["source"].update(block="full_ext")))["status"],
                         "PASS")
        self.assertEqual(run(lambda t: (t.update(notes=[]), cell(t)["source"].update(
            strata=OrderedDict([("sensitivity", "SA1")]))))["status"], "PASS")
        self.assertOnlyFails(run(lambda t: (t.update(notes=[]), cell(t)["source"].update(
            metric_id="R04", strata=OrderedDict([("endpoint", "E02"), ("variant", "test_feedback")])))),
            ["tables"], "without the BL01 note")
        # a degenerate interval shown in the ci column is marked, a marked one is degenerate, the note travels
        # with it (the fixture's 'ci' column has kind ci; 'q06' is a rate and 'gain' a diff column)
        def ci(table):
            return table["rows"][0]["ci"]
        self.assertOnlyFails(run(lambda t: ci(t).update(ci_low=0.4, ci_high=0.4)), ["tables"], "is not marked")
        self.assertOnlyFails(run(lambda t: ci(t).update(ci_low=0.4, ci_high=0.4, ci_degenerate=False)), ["tables"],
                             "is not marked")
        self.assertOnlyFails(run(lambda t: ci(t).update(ci_low=0.4, ci_high=0.4, ci_degenerate=True)), ["tables"],
                             "without the DEGENERATE_CI note")
        result = run(lambda t: (ci(t).update(ci_low=0.4, ci_high=0.4, ci_degenerate=True),
                                t["notes"].append(self.world.notes["DEGENERATE_CI"])))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(check(result, "tables")["detail"]["degenerate_cells"], 1)
        self.assertOnlyFails(run(lambda t: ci(t).update(ci_degenerate=True)), ["tables"], "is not degenerate")
        detail = check(self.world.validate(), "tables")["detail"]
        self.assertEqual((detail["bl01_tables"], detail.get("degenerate_cells", 0)), (1, 0))

    def test_degenerate_marks_only_where_an_interval_is_shown(self):
        """A rate / diff / mean cell prints 'value (n/N)' without its
        interval: a zero-width interval there needs neither the dagger nor
        the DEGENERATE_CI note (the false FAIL on the dry run's T7b), only a
        ci_degenerate flag consistent with the bounds."""
        def run(change, extra=()):
            tables = copy.deepcopy(self.world.tables)
            change(tables[1])
            return self.world.validate(tables=tables + list(extra))

        def q06(table):
            return table["rows"][0]["q06"]
        result = run(lambda t: q06(t).update(ci_low=0.5, ci_high=0.5, ci_degenerate=True))
        self.assertEqual(result["status"], "PASS")
        detail = check(result, "tables")["detail"]
        self.assertEqual((detail.get("degenerate_cells", 0), detail["degenerate_unshown_cells"]), (0, 1))
        # the flag still has to agree with the bounds
        self.assertOnlyFails(run(lambda t: q06(t).update(ci_low=0.5, ci_high=0.5)), ["tables"],
                             "column q06 (kind rate, no interval shown): ci_degenerate False contradicts")
        self.assertOnlyFails(run(lambda t: q06(t).update(ci_degenerate=True)), ["tables"], "contradicts the bounds")
        self.assertOnlyFails(run(lambda t: t["rows"][0]["gain"].update(ci_degenerate=True)), ["tables"],
                             "column gain (kind diff, no interval shown): ci_degenerate True contradicts")
        # a table without any CI column: degenerate rate cells need no note
        source = OrderedDict([("metric_id", "R03"), ("population", "FINAL"), ("block", "full_ext"),
                              ("strata", OrderedDict([("endpoint", "E02"), ("variant", "test_feedback")]))])
        table = self.one_cell_table("T7b_test", "Transitions", source, value=(0, 4), interval=(0.0, 0.0))
        result = run(lambda t: None, [table])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(check(result, "tables")["detail"].get("degenerate_cells", 0), 0)

    def one_cell_table(self, tid, title, source, notes=(), value=(1, 4), interval=(None, None), kind="rate"):
        """A one-row table whose single estimate cell shows `source`."""
        low, high = interval
        estimate = OrderedDict([("numerator", value[0]), ("denominator", value[1]),
                                ("value", float(value[0]) / value[1]), ("ci_low", low), ("ci_high", high),
                                ("ci_degenerate", None if low is None else low == high),
                                ("post_freeze", source["metric_id"] in core.addendum_metric_ids(self.world.addendum)),
                                ("source", source)])
        return OrderedDict([
            ("id", tid), ("title", title), ("population", source["population"]), ("unit", "artifact"),
            ("notes", list(notes)), ("ci_note", None),
            ("columns", [OrderedDict([("key", "label"), ("header", "Label"), ("align", "l"), ("kind", "text")]),
                         OrderedDict([("key", "x"), ("header", "Share % (n/N)"), ("align", "r"), ("kind", kind)])]),
            ("rows", [OrderedDict([("label", "row"), ("x", estimate)])]), ("footnotes", [])])

    def test_bl01_covers_every_q06_e02_aggregate(self):
        """X04 (FINAL / BASE failing Q06), X06 (joint Q06 x E02), G01, E05,
        Q07-Q10, C05 are pilot / composite Q06 / E02 aggregates: without the
        BL01 note their table FAILS; full_ext cells and the static /
        trajectory addendum metrics need none."""
        prefix = validate.table_title_prefix(self.world.addendum)
        bl01 = "BL01: " + self.world.notes["BL01"]

        def source(metric, population, block, **strata):
            return OrderedDict([("metric_id", metric), ("population", population), ("block", block),
                                ("strata", OrderedDict(strata))])

        def run(table):
            return self.world.validate(tables=self.world.tables + [table])
        cases = [("T12_addendum", source("X04", "FINAL", "pilot", variant="static_feedback", state="CLEAN_COMPLETE")),
                 ("T12_addendum", source("X04", "BASE", core.COMPOSITE, state="NO_FINDING_INCOMPLETE")),
                 ("T7c_joint_transitions", source("X06", "FINAL", core.COMPOSITE, variant="test_feedback",
                                                  transition="not_pass->pass",
                                                  heldout_transition="not_all_pass->not_all_pass")),
                 ("T7b_test", source("G01", "FINAL", "pilot", variant="combined_feedback")),
                 ("T7b_test", source("E05", "BASE", core.COMPOSITE)),
                 ("T10_test", source("Q10", "BASE", core.COMPOSITE)),
                 ("T2_test", source("Q07", "BASE", "pilot")),
                 ("T2_test", source("Q08", "BASE", "pilot", verdict="validation_failed")),
                 ("T2_test", source("Q09", "BASE", "pilot")),
                 ("T6b_test", source("C05", "FINAL", core.COMPOSITE, variant="test_feedback",
                                     quantity="per_100_requests")),
                 ("T10_test", source("X01", "FINAL", core.COMPOSITE, endpoint="E02", variant="test_feedback"))]
        for tid, s in cases:
            post = s["metric_id"] in core.addendum_metric_ids(self.world.addendum)
            title = (prefix if post else "") + "Test"
            self.assertOnlyFails(run(self.one_cell_table(tid, title, s)), ["tables"], "without the BL01 note")
            self.assertEqual(run(self.one_cell_table(tid, title, s, notes=[bl01]))["status"], "PASS", (tid, s))
        for tid, s in (("T12_addendum", source("X04", "FINAL", "full_ext", variant="static_feedback",
                                               state="CLEAN_COMPLETE")),
                       ("T7c_joint_transitions", source("X06", "FINAL", "full_ext", variant="test_feedback",
                                                        transition="pass->pass",
                                                        heldout_transition="all_pass->all_pass")),
                       ("T12_addendum", source("X02", "BASE", "pilot", state="DIRTY")),
                       ("T12b_dirty_checks", source("X03", "BASE", core.COMPOSITE, tool="clang_tidy",
                                                    quantity="dirty_only_via_tool")),
                       ("T12_addendum", source("X05", "TRAJECTORIES", "pilot", variant="test_feedback")),
                       ("T2_test", source("Q05", "BASE", "pilot"))):
            self.assertEqual(run(self.one_cell_table(tid, prefix + "Test", s))["status"], "PASS", (tid, s))

    def test_post_freeze_cells_carry_the_post_freeze_label(self):
        prefix = validate.table_title_prefix(self.world.addendum)
        self.assertEqual(prefix, "POST-FREEZE (addendum_1, descriptive): ")
        x04 = OrderedDict([("metric_id", "X04"), ("population", "FINAL"), ("block", "full_ext"),
                           ("strata", OrderedDict([("variant", "static_feedback"), ("state", "CLEAN_COMPLETE")]))])
        x01 = OrderedDict([("metric_id", "X01"), ("population", "FINAL"), ("block", "full_ext"),
                           ("strata", OrderedDict([("endpoint", "Q06"), ("variant", "static_feedback")]))])

        def run(table):
            return self.world.validate(tables=self.world.tables + [table])
        # T12: the title prefix built from the addendum id
        result = run(self.one_cell_table("T12_addendum", "Static DIRTY readings", x04))
        self.assertOnlyFails(result, ["tables"], "does not start with 'POST-FREEZE (addendum_1, descriptive): '")
        self.assertFails(result, "tables", "without the POST-FREEZE label")
        self.assertEqual(run(self.one_cell_table("T12_addendum", prefix + "Static DIRTY readings", x04))["status"],
                         "PASS")
        self.assertOnlyFails(run(self.one_cell_table("T12_addendum", "POST-FREEZE (addendum_2, descriptive): x", x04)),
                             ["tables"], "does not start with")
        self.assertOnlyFails(run(self.one_cell_table("T12_addendum", "Readings", x04, notes=[
            "POST-FREEZE (study_analysis_001.addendum_1): descriptive"])), ["tables"], "does not start with")
        # any other table: the label in the title or the notes (X01 rows next to the frozen R04/R05 of T10)
        self.assertOnlyFails(run(self.one_cell_table("T10_test", "Sensitivity analyses", x01)), ["tables"],
                             "shows 1 post-freeze addendum cell(s) (e.g. X01 full_ext")
        self.assertEqual(run(self.one_cell_table("T10_test", "Sensitivity analyses", x01, notes=[
            "POST-FREEZE (study_analysis_001.addendum_1): X01 rows are descriptive"]))["status"], "PASS")
        self.assertEqual(run(self.one_cell_table("T10_test", "Sensitivity analyses (POST-FREEZE X01)", x01))["status"],
                         "PASS")
        # a cell flagged post_freeze counts even under a frozen metric id
        frozen = self.one_cell_table("T2_test", "Readings", OrderedDict([
            ("metric_id", "F01"), ("population", "BASE"), ("block", "full_ext"),
            ("strata", OrderedDict([("state", "DIRTY")]))]))
        self.assertEqual(run(frozen)["status"], "PASS")
        frozen["rows"][0]["x"]["post_freeze"] = True
        self.assertOnlyFails(run(frozen), ["tables"], "without the POST-FREEZE label")
        detail = check(run(self.one_cell_table("T12_addendum", prefix + "x", x04)), "tables")["detail"]
        self.assertEqual(detail["post_freeze_tables"], 1)

    def test_figures_carry_their_disclosures(self):
        notes = self.world.notes

        def figure(fid, columns=("x", "y"), rows=None, note_ids=(), title="Figure"):
            rows = rows if rows is not None else [OrderedDict((c, 1) for c in columns)]
            return OrderedDict([("id", fid), ("title", title), ("kind", "bars"), ("data_columns", list(columns)),
                                ("data_rows", rows), ("axes", OrderedDict()),
                                ("notes", ["%s: %s" % (n, notes[n]) for n in note_ids]), ("footnotes", [])])

        def run(fig):
            return self.world.validate(figures=self.world.figures + [fig])
        # DESIGN2 2.2 by the fixed ids
        for fid, required in validate.FIGURE_NOTES.items():
            self.assertEqual(run(figure(fid, note_ids=required))["status"], "PASS", fid)
            for missing in required:
                rest = [n for n in required if n != missing]
                self.assertOnlyFails(run(figure(fid, note_ids=rest)), ["figures"],
                                     "figure %s lacks the %s note" % (fid, missing))
        self.assertEqual(set(validate.FIGURE_NOTES["F3_heatmap_model_variant"]), {"BL01", "REASONING"})
        self.assertEqual(validate.FIGURE_NOTES["F4_tool_states"], ("EFFECTIVE_STATES",))
        # a per-model figure needs REASONING; a degenerate data row needs DEGENERATE_CI
        self.assertOnlyFails(run(figure("F9_test", columns=("model", "gain_pp"))), ["figures"],
                             "lacks the REASONING note (per-model data column)")
        self.assertEqual(run(figure("F9_test", columns=("model", "gain_pp"), note_ids=["REASONING"]))["status"], "PASS")
        rows = [OrderedDict([("x", 1), ("ci_degenerate", True)])]
        self.assertOnlyFails(run(figure("F9_test", columns=("x", "ci_degenerate"), rows=rows)), ["figures"],
                             "lacks the DEGENERATE_CI note")
        self.assertEqual(run(figure("F9_test", columns=("x", "ci_degenerate"), rows=rows,
                                    note_ids=["DEGENERATE_CI"]))["status"], "PASS")
        # data rows that name their source: BL01 for a pilot Q06 source, POST-FREEZE for an addendum source
        rows = [OrderedDict([("x", 1), ("source", OrderedDict([("metric_id", "Q06"), ("population", "BASE"),
                                                                ("block", "pilot"), ("strata", OrderedDict())]))])]
        self.assertOnlyFails(run(figure("F9_test", columns=("x", "source"), rows=rows)), ["figures"],
                             "lacks the BL01 note (pilot/composite Q06/E02 source")
        rows = [OrderedDict([("metric_id", "X05"), ("block", "full_ext"), ("strata", OrderedDict([("variant", "v")])),
                             ("value", 1.0)])]
        self.assertOnlyFails(run(figure("F9_test", columns=("metric_id", "block", "strata", "value"), rows=rows)),
                             ["figures"], "figure F9_test shows 1 post-freeze addendum cell(s)")
        self.assertEqual(run(figure("F9_test", columns=("metric_id", "block", "strata", "value"), rows=rows,
                                    title="POST-FREEZE (addendum_1, descriptive): X05"))["status"], "PASS")
        detail = check(run(figure("F3_heatmap_model_variant", columns=("model", "y"),
                                  note_ids=["BL01", "REASONING"])), "figures")["detail"]
        self.assertEqual((detail["bl01_figures"], detail["reasoning_figures"]), (1, 1))

    def test_addendum_statistic_labels(self):
        """The shape labels DESIGN2 section 1 fixes: X01 'difference', X05
        'mean' (per variant) / 'share' (per iteration), X03 finding counts
        'count'."""
        cases = ((("X01", "FINAL", "pilot"), dict(endpoint="Q06", variant="static_feedback"), "share"),
                 (("X01", "FINAL", core.COMPOSITE), dict(endpoint="E02", comparison="static_feedback-test_feedback"),
                  "share"),
                 (("X05", "TRAJECTORIES", "pilot"), dict(variant="test_feedback"), "share"),
                 (("X05", "TRAJECTORIES", "full_ext"), dict(variant="test_feedback", iteration=1), "mean"),
                 (("X03", "BASE", "pilot"), dict(tool="clang_tidy", check_id="bugprone-narrowing-conversions",
                                                 quantity="blocking_findings"), "share"))
        for (metric, population, block), strata, wrong in cases:
            estimates = copy.deepcopy(self.world.estimates)
            find(estimates, metric, population, block, **strata)["statistic"] = wrong
            self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimate_recompute"],
                                 "statistic %r, recomputed" % wrong)
        estimates = copy.deepcopy(self.world.estimates)
        del find(estimates, "X01", "FINAL", "full_ext", endpoint="Q06", variant="test_feedback")["statistic"]
        self.assertOnlyFails(self.world.validate(estimates=estimates), ["estimate_recompute"], "lacks statistic")

    def test_addendum_estimates_without_a_ci_mandate_carry_no_interval(self):
        def with_interval(metric, population, block, fields, **strata):
            estimates = copy.deepcopy(self.world.estimates)
            e = find(estimates, metric, population, block, **strata)
            e.update(fields)
            return self.world.validate(estimates=estimates)
        interval = dict(ci_method=validate.CI_METHOD, replicates=2000, ci_low=0.1, ci_high=0.2, ci_degenerate=False)
        for metric, population, block, strata in (
                ("X05", "TRAJECTORIES", "pilot", dict(variant="test_feedback")),
                ("X06", "FINAL", core.COMPOSITE, dict(variant="static_feedback", transition="not_pass->pass",
                                                      heldout_transition="not_all_pass->not_all_pass")),
                ("X02", "BASE", "full_ext", dict(state="CLEAN_COMPLETE")),
                ("X03", "BASE", "pilot", dict(tool="clang_tidy", quantity="dirty_only_via_tool"))):
            self.assertOnlyFails(with_interval(metric, population, block, interval, **strata),
                                 ["estimate_recompute"], "the addendum defines no interval for this estimate")
        result = with_interval("X06", "FINAL", "pilot", dict(ci_method=validate.CI_METHOD), variant="test_feedback",
                               transition="pass->pass", heldout_transition="all_pass->all_pass")
        self.assertFails(result, "estimate_recompute", "carries ['ci_method']")
        # the CI-mandated shapes may carry their descriptive interval
        for metric, population, block, strata in (("X02", "BASE", "full_ext", dict(state="DIRTY")),
                                                  ("X04", "BASE", "pilot", dict(state="CLEAN_COMPLETE")),
                                                  ("X01", "FINAL", "pilot", dict(endpoint="Q06",
                                                                                 variant="static_feedback"))):
            result = with_interval(metric, population, block, interval, **strata)
            self.assertNotIn("defines no interval", json.dumps(check(result, "estimate_recompute")), metric)
        facts = check(self.world.validate(), "estimate_recompute")["detail"]
        self.assertGreater(facts["addendum_without_ci"], 0)

    def test_addendum_must_be_bound_and_recorded(self):
        foreign = copy.deepcopy(self.world.addendum)
        foreign["amends"]["methodology_canonical_sha256"] = "0" * 64
        result = self.world.validate(addendum=foreign)
        self.assertFails(result, "addendum_bound", "amends methodology")
        self.assertFails(result, "estimates_schema", "input unavailable: addendum")
        extended = copy.deepcopy(self.world.addendum)
        extended["metrics"].append(OrderedDict([("id", "X07"), ("name", "something_new")]))
        self.assertFails(self.world.validate(addendum=extended), "addendum_bound", "X07")
        # a bound addendum other than the manifest's (same metrics, other text)
        edited = copy.deepcopy(self.world.addendum)
        edited["trigger"] = edited["trigger"] + " (edited)"
        self.assertOnlyFails(self.world.validate(addendum=edited), ["input_stability"],
                             "addendum canonical_sha256 (validated vs manifest)")
        # start and end manifest name different addendum states
        with mock.patch.object(core, "git_state", lambda root: git_state()):
            start = manifest.input_manifest(self.world.root, None)
        self.assertEqual(check(self.world.validate(manifest_start=start), "input_stability")["status"], "PASS")
        start["addendum"]["raw_sha256"] = "0" * 64
        start["manifest_sha256"] = core.self_hash(start, "manifest_sha256")
        self.assertOnlyFails(self.world.validate(manifest_start=start), ["input_stability"],
                             "addendum differs between the start and the end manifest")
        self.assertEqual(self.world.manifest["addendum"], core.addendum_identity(self.world.root))
        self.assertEqual(check(self.world.validate(), "addendum_bound")["detail"]["metrics"], list(validate.ADDENDUM_NAMES))


class MetricsCrossCheckTest(unittest.TestCase):
    """The validation's recomputation against the independent implementation
    metrics.py, at the frozen replicate counts, on the metrics test fixture
    (2 pilot benchmarks incl. BL-01 + 3 full_ext benchmarks, two models,
    random verdicts, tool states, findings, gates, trajectories ending at
    0/1/2): every estimate recomputes, every interval the methodology demands
    is present, the exploratory (non-confirmatory) estimate set FAILS."""

    @classmethod
    def setUpClass(cls):
        from thesis.study_analysis import metrics
        from thesis.study_analysis import test_metrics as tm

        cls.metrics = metrics
        cls.methodology = core.load_methodology()
        cls.addendum = core.load_addendum(methodology=cls.methodology)
        cls.tables = tm.synthetic_tables(seed=17)
        cls.dataset = core.Dataset(copy.deepcopy(cls.tables))
        cls.estimates = metrics.compute(cls.dataset, cls.methodology)
        cls.index = validate.Index(cls.dataset)

    def recompute(self, estimates, index=None):
        return validate.recompute_problems(estimates, index or self.index, self.methodology, self.addendum)

    def test_metrics_estimates_pass_every_estimate_check(self):
        problems, facts = self.recompute(self.estimates)
        self.assertEqual(problems, [])
        self.assertEqual(facts["not_recomputed"], 0)
        self.assertEqual(facts["recomputed"], len(self.estimates))
        self.assertEqual(set(facts["recomputed_per_metric"]), set(core.all_metric_ids(self.methodology, self.addendum)))
        self.assertGreater(facts["ci_required"], 100)
        self.assertEqual(facts["ci_required"], facts["ci_present"])
        self.assertEqual(facts["missing_addendum_anchors"], 0)
        self.assertEqual(validate.schema_problems(self.estimates, self.methodology, self.addendum, self.index), [])
        self.assertEqual(validate.bounds_problems(self.estimates), [])
        self.assertEqual(validate.final_step_problems(self.estimates)[0], [])
        self.assertEqual(validate.distribution_problems(self.estimates, self.index)[0], [])
        self.assertEqual(validate.additivity_problems(self.estimates)[0], [])
        self.assertEqual(validate.primary_problems(self.estimates, self.methodology)[0], [])
        rerun = self.metrics.compute_primary(self.dataset, self.methodology)
        self.assertEqual(validate.reproducibility_problems(self.estimates, rerun), [])

    def test_addendum_estimates_of_metrics_py_are_recomputed(self):
        """The producer's X01-X06 against the validation's own code paths,
        including the CI mandate (X01, X02 DIRTY, X04 at the descriptive
        count) and the contract keys."""
        addendum_ids = set(core.addendum_metric_ids(self.addendum))
        post = [e for e in self.estimates if e.get("metric_id") in addendum_ids]
        self.assertEqual(set(e["metric_id"] for e in post), addendum_ids)
        self.assertTrue(all(e["post_freeze"] is True for e in post))
        self.assertTrue(all(e["post_freeze"] is False for e in self.estimates if e["metric_id"] not in addendum_ids))
        problems, facts = self.recompute(self.estimates)
        self.assertEqual([p for p in problems if p.startswith("X0")], [])
        self.assertEqual(facts["missing_addendum_anchors"], 0)
        engine = validate.Recompute(self.index, self.methodology, self.addendum)
        demanded = [e for e in post if validate.ci_required(e) and e["value"] is not None and engine.estimable(e)]
        self.assertEqual(set(e["metric_id"] for e in demanded), set(validate.ADDENDUM_CI_METRICS))
        for e in demanded:
            self.assertEqual(e["ci_method"], validate.CI_METHOD)
            self.assertIsNotNone(e["ci_low"])
        self.assertEqual(validate.bootstrap_problems(demanded[0], self.methodology), [])
        primary = [e for e in self.estimates if e["p_value"] is not None]
        boot = core.statistics_settings(self.methodology)["bootstrap"]
        self.assertEqual(set(round(e["p_resolution"], 12) for e in primary),
                         {round(2.0 / boot["replicates_primary"], 12)})
        self.assertEqual(set(round(e["p_holm_resolution"], 12) for e in primary),
                         {round(len(primary) * 2.0 / boot["replicates_primary"], 12)})
        # tampering with one producer count fails
        estimates = copy.deepcopy(self.estimates)
        e = [x for x in estimates if x["metric_id"] == "X02" and x["strata"].get("state") == "DIRTY"][0]
        e["dirty_only_under_frozen_rule"] += 1
        self.assertTrue(any("dirty_only_under_frozen_rule" in p for p in self.recompute(estimates)[0]))

    def test_exploratory_estimates_fail(self):
        exploratory = self.metrics.compute(self.dataset, self.methodology, 200, 40, exploratory=True)
        schema = validate.schema_problems(exploratory, self.methodology)
        self.assertTrue(any("EXPLORATORY" in p for p in schema))
        self.assertTrue(any("the methodology fixes 2000" in p for p in schema))
        primary = validate.primary_problems(exploratory, self.methodology)[0]
        self.assertEqual(sum(1 for p in primary if "the methodology fixes 10000 (primary family)" in p), 12)
        # the numbers themselves are the same definitions: only the bootstrap settings fail
        self.assertEqual(self.recompute(exploratory)[0], [])

    def test_a_missing_demanded_interval_fails(self):
        estimates = copy.deepcopy(self.estimates)
        e = find(estimates, "Q06", "BASE", core.COMPOSITE)
        self.assertEqual(e["ci_method"], validate.CI_METHOD)
        e["ci_low"] = e["ci_high"] = e["ci_method"] = e["replicates"] = None
        problems = self.recompute(estimates)[0]
        self.assertEqual(len(problems), 1)
        self.assertIn("demands a cluster-bootstrap CI", problems[0])
        # a single-cluster domain (pilot family) carries no interval and none is demanded
        family = core.family_of(self.tables["base_cells"][0]["benchmark"])
        pilot = find(self.estimates, "Q06", "BASE", "pilot", family=family)
        self.assertIsNone(pilot["ci_method"])

    def test_tampered_counts_fail(self):
        cases = [
            (("R01", "FINAL", core.COMPOSITE), dict(endpoint="Q06", variant="static_feedback", transition="pass->not_pass"),
             "numerator", 1),
            (("F05", "GENERATED", core.COMPOSITE), None, "numerator", 7),
            (("F06", "GENERATED", core.COMPOSITE), dict(pair="asan_ubsan+memcheck", **{"class": "memory"}), "n00", 1),
            (("C01", "REPAIR_CANDIDATES", "pilot"), dict(variant="combined_feedback", quantity="records_per_trajectory"),
             "numerator", 1),
            (("C02", "REPAIR_CANDIDATES", "full_ext"), dict(variant="test_feedback", quantity="input_tokens"),
             "numerator", 3),
            (("C03", "REPAIR_CANDIDATES", core.COMPOSITE), dict(variant="static_feedback"), "n", 1),
            (("C04", "GENERATED", core.COMPOSITE), dict(tool="infer", outlier_rule="all"), "timeouts", 1),
        ]
        for (metric, population, block), strata, field, delta in cases:
            estimates = copy.deepcopy(self.estimates)
            if strata is None:
                e = [x for x in estimates if (x["metric_id"], x["population"], x["block"]) == (metric, population, block)
                     and x["strata"].get("quantity") == "findings" and x["numerator"]][0]
            else:
                e = find(estimates, metric, population, block, **strata)
            e[field] += delta
            problems = self.recompute(estimates)[0]
            self.assertTrue(any(metric in p and field in p for p in problems), (metric, field, problems[:3]))

    def test_identical_q06_cohort_across_variants(self):
        tables = copy.deepcopy(self.tables)
        target = [a for a in tables["artifacts"] if a["variant"] == "test_feedback" and a["iteration"] == 1][0]
        target["correctness_verdict"] = "baseline_incompatible"
        dataset = core.Dataset(tables)
        estimates = self.metrics.compute(dataset, self.methodology, 200, 40, exploratory=True)
        index = validate.Index(dataset)
        self.assertEqual(self.recompute(estimates, index)[0], [])
        engine = validate.Recompute(index, self.methodology)
        self.assertFalse(engine.q06_eligible(target["cell_id"]))
        for variant in core.VARIANTS:     # the cell leaves the paired cohort of EVERY variant
            num, den = engine.estimate({"metric_id": "R04", "population": "FINAL", "block": core.COMPOSITE,
                                        "strata": {"endpoint": "Q06", "variant": variant}})
            self.assertEqual(den, len(index.base_of) - 1)
        unpaired = engine.estimate({"metric_id": "Q06", "population": "BASE", "block": core.COMPOSITE, "strata": {}})
        self.assertEqual(unpaired[1], len(index.base_of))


if __name__ == "__main__":
    unittest.main()
