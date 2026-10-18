"""Unit tests of metrics.py on SYNTHETIC datasets that follow core.SCHEMAS.

The generator below builds every normalized table (2 blocks, models, 3
execution models, 3 variants, trajectories ending at iterations 0/1/2,
tool entries with the real applicability pattern, findings, enhanced pairs
with spec-level gates, generations). Its derived artifact columns are
computed by an independent implementation of the methodology rules, so the
tests check metrics.py against the definitions, not against itself. The
expected values are computed by brute force from the raw rows or by hand.

    python3 -B -m unittest -v thesis.study_analysis.test_metrics
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import unittest
from collections import Counter, OrderedDict

from thesis.study_analysis import core, metrics, stats

ALL_EM = core.EXECUTION_MODELS
APPLIES = OrderedDict([("compiler", ALL_EM), ("gcc_analyzer", ALL_EM), ("clang_tidy", ALL_EM),
                       ("cppcheck", ALL_EM), ("infer", ("serial", "mpi")), ("parcoach", ("mpi",)),
                       ("llov", ("omp",)), ("asan_ubsan", ALL_EM), ("tsan", ("omp",)),
                       ("memcheck", ("serial", "omp")), ("must", ("mpi",))])
STAGE = OrderedDict([(t, "static") for t in core.STATIC_TOOLS] + [(t, "dynamic") for t in core.DYNAMIC_TOOLS])
FAMILIES = ("memory", "uninitialized", "null_deref", "race", "deadlock", "mpi_usage", "other")
PILOT_BENCHMARKS = (core.BL01_BENCHMARK, "fft/05_fft_one")
FULL_BENCHMARKS = ("dense_la/01_dense_la_two", "fft/06_fft_three", "sort/40_sort_four")
MODELS = ("model_a", "model_b")
RUN_PATTERN = OrderedDict([("pilot", core.PILOT + "__%s__iter%d"), ("full_ext", "full_ext_recovery_004__%s__iter%d")])
OWNER = OrderedDict([("pilot", core.PILOT), ("full_ext", "full_ext_recovery_004")])
PRIMARY, DESCRIPTIVE = 200, 40
# the addendum_1 contract wording (DESIGN2 section 1), spelled out here instead of imported from metrics.py
POST_FREEZE = "POST-FREEZE addendum_1 (descriptive): "
DEGENERATE = "degenerate percentile interval (zero width): every supporting cluster at the boundary"
NEW_KEYS = ("post_freeze", "ci_degenerate", "p_resolution", "p_holm_resolution")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pick(rng, weighted):
    total = float(sum(w for _, w in weighted))
    x = rng.random() * total
    for value, weight in weighted:
        x -= weight
        if x < 0:
            return value
    return weighted[-1][0]


# -- independent derivation of the artifact columns (methodology finding_rules) ----------------------

def _verdict3(group):
    group = [e for e in group if e["applicable"]]
    if sum(e["num_reported_blocking"] for e in group) > 0:
        return "DIRTY"
    if all(e["state"] == "COMPLETED" for e in group):
        return "CLEAN_COMPLETE"
    return "NO_FINDING_INCOMPLETE"


def derive(artifact, entries, pairs):
    static = [e for e in entries if e["stage"] == "static" and e["tool"] != "compiler"]
    dynamic = [e for e in entries if e["stage"] == "dynamic"]
    compiler = [e for e in entries if e["tool"] == "compiler"][0]
    artifact["static_three_state"] = _verdict3(static)
    artifact["dynamic_three_state"] = _verdict3(dynamic)
    artifact["compile_error"] = compiler["num_reported_blocking"] >= 1
    artifact["static_analysis_complete"] = all(e["state"] == "COMPLETED" for e in static if e["applicable"])
    artifact["dynamic_analysis_complete"] = all(e["state"] == "COMPLETED" for e in dynamic if e["applicable"])
    artifact["low_confidence_any"] = any(e["num_low_confidence"] > 0 for e in entries)
    flags = [artifact["clean_" + f] for f in core.CLEANING_FLAGS]
    artifact["clean_any"] = any(artifact["clean_" + f] for f in core.CLEANING_FLAGS if f != "used_fence")
    artifact["clean_any_including_fence"] = any(flags)
    statuses = Counter(p["status"] for p in pairs)
    gated = sum(1 for p in pairs if p["status"] in ("baseline_incompatible", "numerically_unstable"))
    artifact["enh_pairs"] = len(pairs)
    artifact["enh_gated"] = gated
    artifact["enh_valid"] = len(pairs) - gated
    for status in ("pass", "fail", "build_failed", "crash", "timeout", "runtime_error"):
        artifact["enh_" + status] = statuses[status]
    valid = len(pairs) - gated
    artifact["enh_all_pass"] = None if valid == 0 else (1 if statuses["pass"] == valid else 0)


def refresh(tables):
    """Recompute every derived artifact column (and entry counts) after a
    test edited raw rows."""
    findings = Counter((f["artifact_id"], f["tool"], f["kind"]) for f in tables["findings"])
    for e in tables["tool_entries"]:
        for kind in core.FINDING_KINDS:
            e["num_" + kind] = findings[(e["artifact_id"], e["tool"], kind)]
        e["num_findings"] = sum(e["num_" + k] for k in core.FINDING_KINDS)
    entries = OrderedDict()
    for e in tables["tool_entries"]:
        entries.setdefault(e["artifact_id"], []).append(e)
    pairs = OrderedDict()
    for p in tables["enhanced_pairs"]:
        pairs.setdefault(p["artifact_id"], []).append(p)
    for a in tables["artifacts"]:
        derive(a, entries.get(a["artifact_id"], []), pairs.get(a["artifact_id"], []))
    return tables


# -- generator --------------------------------------------------------------------------------------

class _Generator(object):

    def __init__(self, seed, pairs, findings_max, final_plan, verdict_plan, tool_plan, enh_plan, absent_pilot,
                 gate_share, clean_plan=None):
        self.rng = random.Random(seed)
        self.seed = seed
        self.pairs = pairs
        self.findings_max = findings_max
        self.final_plan = final_plan or self._final
        self.verdict_plan = verdict_plan or self._verdict
        self.tool_plan = tool_plan or self._tool
        self.enh_plan = enh_plan or self._enh
        self.absent = absent_pilot
        self.gate_share = gate_share
        self.clean_plan = clean_plan
        self.tables = OrderedDict((name, []) for name in core.SCHEMAS)

    def _final(self, cell, variant, rng):
        final = _pick(rng, [(0, 3), (1, 1), (2, 1)])
        if final == core.MAX_ITERATIONS:
            status = _pick(rng, [("stopped_budget", 3), ("stopped_clean", 1), ("stopped_tests_pass", 1),
                                 ("stopped_analysis_incomplete", 1)])
        else:
            status = _pick(rng, [("stopped_clean", 2), ("stopped_tests_pass", 2), ("stopped_analysis_incomplete", 2),
                                 ("repair_unusable", 1)])
        return final, status

    def _verdict(self, artifact, rng):
        return _pick(rng, [("pass", 6), ("build_failed", 1), ("validation_failed", 2), ("runtime_error", 1),
                           ("timeout", 1)])

    def _tool(self, artifact, tool, rng):
        if tool == "compiler":
            state = "COMPLETED"
            found = [("build", "reported_blocking")] if artifact["correctness_verdict"] == "build_failed" else []
            return state, found
        state = _pick(rng, [("COMPLETED", 14), ("PARTIAL", 2), ("TIMEOUT", 1), ("TOOL_ERROR", 2),
                            ("NOT_ANALYZED", 1)])
        found = []
        for _ in range(rng.randint(0, self.findings_max)):
            kind = _pick(rng, [("reported_blocking", 2), ("low_confidence", 1), ("non_blocking", 7)])
            found.append((rng.choice(FAMILIES), kind))
        return state, found

    def _enh(self, artifact, key, rng):
        if artifact["correctness_verdict"] == "build_failed":
            return "build_failed"
        return _pick(rng, [("pass", 30), ("fail", 3), ("build_failed", 1), ("crash", 1), ("timeout", 1),
                           ("runtime_error", 1)])

    def _gate(self, block, benchmark, key, em):
        rng = random.Random("%s|%s|%s|%s|%s" % (self.seed, block, benchmark, key, em))
        if rng.random() < self.gate_share:
            return rng.choice(core.ENHANCED_GATED)
        return None

    def artifact(self, cell, variant, iteration, run, owner):
        rng = self.rng
        aid = core.artifact_id(cell["block"], cell["model_id"], run, cell["sample_id"])
        a = OrderedDict((column, None) for column in core.SCHEMAS["artifacts"])
        a.update(OrderedDict([
            ("artifact_id", aid), ("cell_id", cell["cell_id"]), ("block", cell["block"]),
            ("model_id", cell["model_id"]), ("benchmark", cell["benchmark"]), ("family", cell["family"]),
            ("execution_model", cell["execution_model"]), ("sample_id", cell["sample_id"]), ("variant", variant),
            ("iteration", iteration), ("source_run", run), ("loop_owner", owner), ("source_sha256", _sha(aid)),
            ("generation_success", True), ("assembled", rng.random() > 0.03),
            ("generation_truncated", rng.random() < 0.05)]))
        for flag in core.CLEANING_FLAGS:
            a["clean_" + flag] = rng.random() < (0.3 if flag == "used_fence" else 0.08)
        if self.clean_plan is not None:              # after the draws: the default rng sequence is unchanged
            for flag, value in self.clean_plan(a).items():
                a["clean_" + flag] = value
        a["correctness_verdict"] = self.verdict_plan(a, rng)
        a["build_ok"] = a["correctness_verdict"] != "build_failed"
        for column in ("correctness_owner", "static_owner", "dynamic_owner", "enhanced_owner"):
            a[column] = run
        a["static_supplemented_by"] = OrderedDict()
        entries = []
        for tool, models in APPLIES.items():
            applicable = cell["execution_model"] in models
            if applicable:
                state, found = self.tool_plan(a, tool, rng)
            elif STAGE[tool] == "static" and cell["block"] == "pilot" and self.absent > 0:
                self.absent -= 1
                state, found = "ABSENT_INAPPLICABLE", []
            else:
                state, found = "NOT_APPLICABLE", []
            ran = state not in core.INAPPLICABLE_STATES
            if state == "ABSENT_INAPPLICABLE":
                duration = None
            elif state == "TIMEOUT":
                duration = 300.0
            elif ran:
                duration = round(rng.uniform(0.1, 60.0), 3)
            else:
                duration = 0.0
            kinds = Counter(item[1] for item in found)
            entry = OrderedDict([
                ("artifact_id", aid), ("stage", STAGE[tool]), ("tool", tool), ("applicable", applicable),
                ("state", state), ("ran", ran), ("duration_seconds", duration), ("num_findings", len(found)),
                ("num_reported_blocking", kinds["reported_blocking"]), ("num_low_confidence", kinds["low_confidence"]),
                ("num_non_blocking", kinds["non_blocking"]), ("owner", run)])
            entries.append(entry)
            for i, item in enumerate(found):
                family, kind = item[:2]
                check = item[2] if len(item) > 2 else "%s-check-%d" % (tool, i)      # (family, kind[, check_id])
                self.tables["findings"].append(OrderedDict([
                    ("artifact_id", aid), ("stage", STAGE[tool]), ("tool", tool),
                    ("check_id", check),
                    ("family", family), ("severity", "error" if kind == "reported_blocking" else "warning"),
                    ("kind", kind), ("line", rng.randint(1, 80))]))
        pairs = []
        for j in range(self.pairs):
            key = json.dumps({"size": j, "pattern": "random"}, sort_keys=True, separators=(",", ":"))
            gated = self._gate(cell["block"], cell["benchmark"], key, cell["execution_model"])
            status = gated if gated is not None else self.enh_plan(a, key, rng)
            pairs.append(OrderedDict([
                ("artifact_id", aid), ("spec_key", key), ("size", j), ("pattern", "random"),
                ("spec_source", "static" if j % 2 == 0 else "llm"), ("status", status),
                ("gated", status in core.ENHANCED_GATED), ("duration_seconds", round(rng.uniform(0.001, 2.0), 3))]))
        derive(a, entries, pairs)
        self.tables["artifacts"].append(a)
        self.tables["tool_entries"].extend(entries)
        self.tables["enhanced_pairs"].extend(pairs)
        direct = iteration > 0 or rng.random() < 0.5
        self.tables["generations"].append(OrderedDict([
            ("artifact_id", aid), ("kind", "base" if iteration == 0 else "repair"),
            ("provider", "provider_" + cell["model_id"]), ("success", True),
            ("timing_mode", "direct" if direct else "batch"),
            ("duration_seconds", round(rng.uniform(1.0, 90.0), 3) if direct else None),
            ("input_tokens", rng.randint(100, 3000)), ("output_tokens", rng.randint(20, 6000)),
            ("reasoning_tokens", None if rng.random() < 0.2 else rng.randint(0, 4000)),
            ("request_chars", rng.randint(500, 9000) if iteration else None), ("finish_reason", "stop")]))
        return a

    def build(self, blocks, models):
        for block, benchmarks in blocks.items():
            for model in models:
                for benchmark in benchmarks:
                    for em in core.EXECUTION_MODELS:
                        sample = "%s__%s__%s__sample_0" % (model, benchmark.replace("/", "__"), em)
                        cell = OrderedDict([
                            ("cell_id", core.cell_id(block, model, sample)), ("block", block), ("model_id", model),
                            ("benchmark", benchmark), ("family", core.family_of(benchmark)), ("execution_model", em),
                            ("sample_id", sample), ("base_run", core.BLOCK_BASE_RUN[block]),
                            ("source_sha256", _sha(sample)), ("bl01", benchmark == core.BL01_BENCHMARK)])
                        self.tables["base_cells"].append(cell)
                        base = self.artifact(cell, "", 0, core.BLOCK_BASE_RUN[block], "")
                        for variant in core.VARIANTS:
                            final, status = self.final_plan(cell, variant, self.rng)
                            ids = [base["artifact_id"]]
                            for k in range(1, final + 1):
                                art = self.artifact(cell, variant, k, RUN_PATTERN[block] % (variant, k), OWNER[block])
                                ids.append(art["artifact_id"])
                            row = OrderedDict([
                                ("trajectory_id", core.trajectory_id(cell["cell_id"], variant)),
                                ("cell_id", cell["cell_id"]), ("block", block), ("model_id", model),
                                ("variant", variant), ("loop_owner", OWNER[block]), ("loop_kind", "native"),
                                ("final_iteration", final), ("terminal_status", status), ("stop_reason", "synthetic")])
                            for k in range(core.MAX_ITERATIONS + 1):
                                row["status_iter%d" % k] = "" if k > final else (status if k == final else "active")
                            row["test_verdict_final"] = ""
                            for k in range(core.MAX_ITERATIONS + 1):
                                row["artifact_iter%d" % k] = ids[k] if k <= final else ""
                            row["final_artifact"] = ids[final]
                            row["request_rounds"] = final + (1 if final and self.rng.random() < 0.2 else 0)
                            self.tables["trajectories"].append(row)
        return self.tables


def synthetic_tables(pilot=PILOT_BENCHMARKS, full_ext=FULL_BENCHMARKS, models=MODELS, pairs=4, seed=5,
                     findings_max=3, final_plan=None, verdict_plan=None, tool_plan=None, enh_plan=None,
                     absent_pilot=3, gate_share=0.15, clean_plan=None):
    generator = _Generator(seed, pairs, findings_max, final_plan, verdict_plan, tool_plan, enh_plan, absent_pilot,
                           gate_share, clean_plan)
    return generator.build(OrderedDict([("pilot", pilot), ("full_ext", full_ext)]), models)


def synthetic_dataset(**kwargs):
    return core.Dataset(synthetic_tables(**kwargs), OrderedDict([("source", "synthetic")]))


def index(estimates):
    return OrderedDict(((e["metric_id"], e["population"], e["block"], json.dumps(e["strata"])), e) for e in estimates)


def strata_json(**pairs):
    return json.dumps(metrics.make_strata(pairs.items()))


class Raw(object):
    """Brute-force view of the raw synthetic rows for the addendum metrics
    (independent of metrics.py: trajectories are read directly, the static
    three-state and the tool-verdict reading are recomputed from findings)."""

    ANALYSIS = core.STATIC_ANALYSIS_TOOLS
    VERDICT_STATES = ("COMPLETED", "PARTIAL")             # the addendum text: "COMPLETED or PARTIAL"

    def __init__(self, tables):
        self.tables = tables
        self.arts = OrderedDict((a["artifact_id"], a) for a in tables["artifacts"])
        self.cells = OrderedDict((c["cell_id"], c) for c in tables["base_cells"])
        self.trajs = OrderedDict(((t["cell_id"], t["variant"]), t) for t in tables["trajectories"])
        self.base = OrderedDict((a["cell_id"], a) for a in tables["artifacts"] if a["iteration"] == 0)
        self.entries = {}
        for e in tables["tool_entries"]:
            self.entries.setdefault(e["artifact_id"], {})[e["tool"]] = e
        self.blocking = Counter()                          # (artifact, tool) -> reported blocking findings
        self.checks = Counter()                            # (artifact, tool, check) -> reported blocking findings
        for f in tables["findings"]:
            if f["kind"] == "reported_blocking":
                self.blocking[(f["artifact_id"], f["tool"])] += 1
                self.checks[(f["artifact_id"], f["tool"], f["check_id"])] += 1
        clusters = OrderedDict()
        for c in tables["base_cells"]:
            clusters[c["benchmark"]] = c["block"]
        self.clusters = OrderedDict((b, clusters[b]) for b in sorted(clusters))

    def in_block(self, row, block):
        return block == core.COMPOSITE or row["block"] == block

    def final(self, cid, variant):
        return self.arts[self.trajs[(cid, variant)]["final_artifact"]]

    def on_trajectories(self, cid):
        out = [self.base[cid]]
        for v in core.VARIANTS:
            t = self.trajs[(cid, v)]
            out.extend(self.arts[t["artifact_iter%d" % k]] for k in range(1, t["final_iteration"] + 1))
        return out

    @staticmethod
    def y(endpoint, a):
        return int(a["correctness_verdict"] == "pass") if endpoint == "Q06" else int(a["enh_all_pass"] == 1)

    def paired(self, endpoint, cid):
        if endpoint == "Q06":
            return all(a["correctness_verdict"] != "baseline_incompatible" for a in self.on_trajectories(cid))
        return self.base[cid]["enh_valid"] > 0

    def static_state(self, aid, verdict_reading=False):
        rows = [self.entries[aid][t] for t in self.ANALYSIS if self.entries[aid][t]["applicable"]]
        if any(self.blocking[(aid, e["tool"])] and (not verdict_reading or e["state"] in self.VERDICT_STATES)
               for e in rows):
            return "DIRTY"
        if all(e["state"] == "COMPLETED" for e in rows):
            return "CLEAN_COMPLETE"
        return "NO_FINDING_INCOMPLETE"

    def x01(self, block, endpoint, variant=None, comparison=None):
        """(numerator, denominator, excluded, per-cluster {benchmark: (num, den)})."""
        num = den = excluded = 0
        per = OrderedDict()
        for cid, cell in self.cells.items():
            if not self.in_block(cell, block):
                continue
            closed = any(a["clean_auto_closed"] for a in self.on_trajectories(cid))
            if closed or not self.paired(endpoint, cid):
                excluded += 1
                continue
            if variant is not None:
                d = self.y(endpoint, self.final(cid, variant)) - self.y(endpoint, self.base[cid])
            else:
                v1, v2 = comparison
                d = self.y(endpoint, self.final(cid, v1)) - self.y(endpoint, self.final(cid, v2))
            num += d
            den += 1
            pair = per.setdefault(cell["benchmark"], [0, 0])
            pair[0] += d
            pair[1] += 1
        return num, den, excluded, OrderedDict((b, tuple(p)) for b, p in per.items())


# -- tests ------------------------------------------------------------------------------------------

class SyntheticMetricsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.methodology = core.load_methodology()
        cls.addendum = core.load_addendum(methodology=cls.methodology)
        cls.tables = synthetic_tables()
        cls.dataset = core.Dataset(copy.deepcopy(cls.tables))
        # addendum=None: compute loads the repository addendum bound to the frozen methodology
        cls.estimates = metrics.compute(cls.dataset, cls.methodology, PRIMARY, DESCRIPTIVE, exploratory=True)
        cls.by = index(cls.estimates)
        cls.co = metrics.cohorts(core.Dataset(copy.deepcopy(cls.tables)))
        cls.raw = Raw(cls.tables)

    def get(self, metric, population, block, **strata):
        return self.by[(metric, population, block, strata_json(**strata))]

    def rows(self, block):
        return [a for a in self.tables["artifacts"] if block == core.COMPOSITE or a["block"] == block]

    def test_metric_id_set_equals_methodology(self):
        expected = core.all_metric_ids(self.methodology, self.addendum)
        self.assertEqual(set(e["metric_id"] for e in self.estimates), set(expected))
        self.assertEqual(expected[-6:], ["X01", "X02", "X03", "X04", "X05", "X06"])

    def test_sorted_unique_complete_keys(self):
        keys = [metrics.sort_key(e) for e in self.estimates]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))
        required = ("metric_id", "population", "block", "strata", "numerator", "denominator", "value", "ci_low",
                    "ci_high", "ci_method", "replicates", "p_value", "p_holm", "reject_holm", "note")
        for e in self.estimates:
            self.assertEqual(tuple(e)[:len(required)], required)
            self.assertTrue(all(k in e for k in NEW_KEYS), metrics.sort_key(e))
            self.assertIsInstance(e["post_freeze"], bool)
            self.assertIn(e["block"], ("pilot", "full_ext", "composite"))
            if e["statistic"] == "share" and e["value"] is not None:
                self.assertLessEqual(e["numerator"], e["denominator"])
                self.assertTrue(0.0 <= e["value"] <= 1.0)
            if e["ci_method"] is not None:
                self.assertLessEqual(e["ci_low"], e["ci_high"])

    def test_deterministic_across_runs(self):
        again = metrics.compute(core.Dataset(copy.deepcopy(self.tables)), self.methodology, PRIMARY, DESCRIPTIVE,
                                exploratory=True)
        self.assertEqual(json.dumps(again), json.dumps(self.estimates))

    def test_identical_cohorts_and_final_equals_step2(self):
        for block in ("pilot", "full_ext", "composite"):
            base = self.get("Q06", "BASE", block)
            sizes = set()
            for v in core.VARIANTS:
                final = self.get("Q06", "FINAL", block, variant=v)
                step2 = self.get("Q06", "STEP", block, variant=v, step=2)
                step0 = self.get("Q06", "STEP", block, variant=v, step=0)
                for key in ("numerator", "denominator", "value", "ci_low", "ci_high"):
                    self.assertEqual(final[key], step2[key])
                    self.assertEqual(step0[key], base[key])
                sizes.add(final["denominator"])
                sizes.add(self.get("Q06", "STEP", block, variant=v, step=1)["denominator"])
                self.assertEqual(self.get("R04", "FINAL", block, endpoint="Q06", variant=v)["denominator"],
                                 base["denominator"])
            self.assertEqual(sizes, {base["denominator"]})
            cells = len([c for c in self.tables["base_cells"] if block == "composite" or c["block"] == block])
            self.assertEqual(base["denominator"], cells)                      # no baseline_incompatible

    def test_step_selection_carries_last_artifact_forward(self):
        for t in self.tables["trajectories"]:
            for k in range(3):
                art = self.co["step"][t["variant"]][k][t["cell_id"]]
                self.assertEqual(art["artifact_id"], t["artifact_iter%d" % min(k, t["final_iteration"])])
            self.assertEqual(self.co["final"][t["variant"]][t["cell_id"]]["artifact_id"], t["final_artifact"])

    def test_brute_force_rates(self):
        for block in ("pilot", "full_ext", "composite"):
            arts = [a for a in self.rows(block) if a["iteration"] == 0]
            q06 = self.get("Q06", "BASE", block)
            self.assertEqual((q06["numerator"], q06["denominator"]),
                             (sum(a["correctness_verdict"] == "pass" for a in arts), len(arts)))
            omp = [a for a in arts if a["execution_model"] == "omp" and a["model_id"] == "model_b"]
            q06 = self.get("Q06", "BASE", block, model_id="model_b", execution_model="omp")
            self.assertEqual(q06["numerator"], sum(a["correctness_verdict"] == "pass" for a in omp))
            ids = set(a["artifact_id"] for a in arts)
            valid = [p for p in self.tables["enhanced_pairs"] if p["artifact_id"] in ids and not p["gated"]]
            e01 = self.get("E01", "ENH_PAIRS(BASE)", block)
            self.assertEqual(e01["denominator"], len(valid))
            self.assertEqual(e01["numerator"], sum(p["status"] == "pass" for p in valid))
            per = Counter(p["artifact_id"] for p in valid)
            passing = Counter(p["artifact_id"] for p in valid if p["status"] == "pass")
            e02 = self.get("E02", "BASE", block)
            self.assertEqual(e02["denominator"], len(per))
            self.assertEqual(e02["numerator"], sum(1 for aid, n in per.items() if passing[aid] == n))
            self.assertEqual(e02["excluded"], len(arts) - len(per))
            gen = self.rows(block)
            q05 = self.get("Q05", "GENERATED", block)
            self.assertEqual((q05["numerator"], q05["denominator"]), (sum(a["build_ok"] for a in gen), len(gen)))
            it1 = self.get("Q06", "GENERATED", block, iteration=1)
            self.assertEqual(it1["denominator"], sum(1 for a in gen if a["iteration"] == 1))
            built = [a for a in arts if a["build_ok"]]
            q07 = self.get("Q07", "BASE", block)
            self.assertEqual((q07["numerator"], q07["denominator"]),
                             (sum(a["correctness_verdict"] == "pass" for a in built), len(built)))
            raw = [a for a in arts if a["assembled"] and not a["clean_any_including_fence"]]
            q09 = self.get("Q09", "BASE", block)
            self.assertEqual(q09["denominator"], len(raw))
            assembled = [a for a in arts if a["assembled"]]
            q04 = self.get("Q04", "BASE", block, flag="any")
            self.assertEqual((q04["numerator"], q04["denominator"]),
                             (sum(a["clean_any"] for a in assembled), len(assembled)))

    def _paired_truth(self, block, variant, endpoint="Q06"):
        def y(a):
            return int(a["correctness_verdict"] == "pass") if endpoint == "Q06" else int(a["enh_all_pass"] == 1)
        out = Counter()
        for cid, cell in self.co["cells"].items():
            if block != "composite" and cell["block"] != block:
                continue
            b = self.co["base"][cid]
            if endpoint == "E02" and b["enh_valid"] == 0:
                continue
            f = self.co["final"][variant][cid]
            out["cells"] += 1
            out["base_fail"] += 1 - y(b)
            out["base_pass"] += y(b)
            out["improved"] += int(y(b) == 0 and y(f) == 1)
            out["regressed"] += int(y(b) == 1 and y(f) == 0)
        return out

    def test_repair_counts_and_terminal_status_is_not_success(self):
        for block in ("pilot", "full_ext", "composite"):
            for endpoint in ("Q06", "E02"):
                for v in core.VARIANTS:
                    truth = self._paired_truth(block, v, endpoint)
                    r02 = self.get("R02", "FINAL", block, endpoint=endpoint, variant=v)
                    r03 = self.get("R03", "FINAL", block, endpoint=endpoint, variant=v)
                    r04 = self.get("R04", "FINAL", block, endpoint=endpoint, variant=v)
                    self.assertEqual((r02["numerator"], r02["denominator"]), (truth["improved"], truth["base_fail"]))
                    self.assertEqual((r03["numerator"], r03["denominator"]), (truth["regressed"], truth["base_pass"]))
                    self.assertEqual((r04["numerator"], r04["denominator"]),
                                     (truth["improved"] - truth["regressed"], truth["cells"]))
                    unchanged = truth["cells"] - truth["improved"] - truth["regressed"]
                    self.assertGreaterEqual(unchanged, 0)
        # stopped_clean / stopped_tests_pass trajectories with a failing base and final artifact exist in the
        # fixture: counting terminal statuses as success would change R02.
        naive = 0
        for t in self.tables["trajectories"]:
            if t["terminal_status"] in ("stopped_clean", "stopped_tests_pass"):
                b = self.co["base"][t["cell_id"]]
                f = self.co["final"][t["variant"]][t["cell_id"]]
                if b["correctness_verdict"] != "pass" and f["correctness_verdict"] != "pass":
                    naive += 1
        self.assertGreater(naive, 0)

    def test_transition_matrices_sum_to_cohort(self):
        for block in ("pilot", "full_ext", "composite"):
            for endpoint, states in metrics.ENDPOINT_STATES.items():
                for v in core.VARIANTS:
                    rows = [self.get("R01", "FINAL", block, endpoint=endpoint, variant=v,
                                     transition="%s->%s" % (x, y)) for x in states for y in states]
                    dens = set(r["denominator"] for r in rows)
                    self.assertEqual(len(dens), 1)
                    self.assertEqual(sum(r["numerator"] for r in rows), dens.pop())
                    if endpoint in ("Q06", "E02"):
                        truth = self._paired_truth(block, v, endpoint)
                        self.assertEqual(rows[0]["denominator"], truth["cells"])
                        self.assertEqual(rows[2]["numerator"], truth["improved"])    # not_pass -> pass
                        self.assertEqual(rows[1]["numerator"], truth["regressed"])   # pass -> not_pass
                    step = [self.get("R01", "STEP", block, endpoint=endpoint, variant=v, step=1,
                                     transition="%s->%s" % (x, y)) for x in states for y in states]
                    self.assertEqual(sum(r["numerator"] for r in step), step[0]["denominator"])

    def test_variant_difference_matches_final_rates(self):
        for block in ("pilot", "full_ext", "composite"):
            for v1, v2 in metrics.COMPARISONS:
                r05 = self.get("R05", "FINAL", block, endpoint="Q06", comparison="%s-%s" % (v1, v2))
                a = self.get("Q06", "FINAL", block, variant=v1)
                b = self.get("Q06", "FINAL", block, variant=v2)
                self.assertEqual(r05["numerator"], a["numerator"] - b["numerator"])
                self.assertAlmostEqual(r05["value"], a["value"] - b["value"])

    def test_enhanced_distribution_and_gated_groups(self):
        for block in ("pilot", "full_ext", "composite"):
            ids = set(a["artifact_id"] for a in self.rows(block))
            pairs = [p for p in self.tables["enhanced_pairs"] if p["artifact_id"] in ids]
            e04 = self.get("E04", "ENH_PAIRS(GENERATED)", block)
            self.assertEqual((e04["numerator"], e04["denominator"]), (sum(p["gated"] for p in pairs), len(pairs)))
            arts = OrderedDict((a["artifact_id"], a) for a in self.tables["artifacts"])
            groups = set()
            gated = set()
            for p in pairs:
                a = arts[p["artifact_id"]]
                g = (a["block"], a["benchmark"], p["spec_key"], a["execution_model"])
                groups.add(g)
                if p["gated"]:
                    gated.add(g)
            self.assertEqual((e04["groups"], e04["gated_groups"]), (len(groups), len(gated)))
            self.assertGreater(len(gated), 0)
            total = 0
            for status in core.ENHANCED_STATUSES:
                e03 = self.get("E03", "ENH_PAIRS(GENERATED)", block, status=status)
                self.assertEqual(e03["numerator"], sum(p["status"] == status for p in pairs))
                total += e03["numerator"]
            self.assertEqual(total, len(pairs))

    def test_inapplicable_excluded_from_coverage(self):
        base = [a for a in self.tables["artifacts"] if a["iteration"] == 0]
        ids = set(a["artifact_id"] for a in base)
        entries = [e for e in self.tables["tool_entries"] if e["artifact_id"] in ids]
        absent = [e for e in entries if e["state"] == "ABSENT_INAPPLICABLE"]
        self.assertGreater(len(absent), 0)
        for tool in APPLIES:
            mine = [e for e in entries if e["tool"] == tool]
            s02 = self.get("S02" if STAGE[tool] == "static" else "D02", "BASE", "composite", tool=tool)
            applicable = [e for e in mine if e["state"] not in ("NOT_APPLICABLE", "ABSENT_INAPPLICABLE")]
            self.assertEqual(s02["denominator"], len(applicable))
            self.assertEqual(s02["numerator"], sum(e["state"] == "COMPLETED" for e in applicable))
            for state in core.TOOL_STATES:
                s01 = self.get("S01" if STAGE[tool] == "static" else "D01", "BASE", "composite", tool=tool,
                               state=state)
                self.assertEqual(s01["numerator"], sum(e["state"] == state for e in mine))
                self.assertEqual(s01["denominator"], len(base))
        llov_mpi = self.get("S02", "BASE", "composite", tool="llov", execution_model="mpi")
        self.assertEqual((llov_mpi["denominator"], llov_mpi["value"]), (0, None))

    def test_three_state_shares_and_dirty_ci(self):
        base = [a for a in self.tables["artifacts"] if a["iteration"] == 0]
        for state in core.THREE_STATE:
            f01 = self.get("F01", "BASE", "composite", state=state)
            self.assertEqual(f01["numerator"], sum(a["static_three_state"] == state for a in base))
            self.assertEqual(f01["ci_method"] is not None, state == "DIRTY")
        incomplete = [a for a in base if a["static_three_state"] == "NO_FINDING_INCOMPLETE"]
        self.assertGreater(len(incomplete), 0)

    def test_partial_without_finding_is_not_clean(self):
        entry = lambda tool, state, rb=0: OrderedDict([("tool", tool), ("applicable", True), ("state", state),  # noqa
                                                       ("num_reported_blocking", rb)])
        self.assertEqual(metrics.three_state([entry("gcc_analyzer", "PARTIAL"), entry("cppcheck", "COMPLETED")]),
                         "NO_FINDING_INCOMPLETE")
        self.assertEqual(metrics.three_state([entry("gcc_analyzer", "PARTIAL", 1)]), "DIRTY")
        self.assertEqual(metrics.three_state([entry("cppcheck", "COMPLETED")]), "CLEAN_COMPLETE")
        na = OrderedDict([("tool", "llov"), ("applicable", False), ("state", "NOT_APPLICABLE"),
                          ("num_reported_blocking", 0)])
        self.assertEqual(metrics.three_state([entry("cppcheck", "COMPLETED"), na]), "CLEAN_COMPLETE")
        tables = copy.deepcopy(self.tables)
        victim = [a for a in tables["artifacts"] if a["static_three_state"] == "NO_FINDING_INCOMPLETE"][0]
        victim["static_three_state"] = "CLEAN_COMPLETE"          # a PARTIAL/gap without finding claimed clean
        with self.assertRaises(core.AnalysisRefused):
            metrics.compute(core.Dataset(tables), self.methodology, 5, 5, exploratory=True)

    def test_findings_counts_per_tool(self):
        ids = set(a["artifact_id"] for a in self.tables["artifacts"] if a["iteration"] == 0)
        f = [x for x in self.tables["findings"] if x["artifact_id"] in ids and x["tool"] == "clang_tidy"
             and x["family"] == "memory" and x["kind"] == "non_blocking"]
        est = self.get("F05", "BASE", "composite", tool="clang_tidy", family="memory", kind="non_blocking",
                       quantity="findings")
        self.assertEqual(est["numerator"], len(f))
        share = self.get("F05", "BASE", "composite", tool="clang_tidy", family="memory", kind="non_blocking",
                         quantity="artifacts_with_finding")
        self.assertEqual(share["numerator"], len(set(x["artifact_id"] for x in f)))
        self.assertEqual(share["denominator"], len(ids))

    def test_tool_agreement_2x2(self):
        arts = OrderedDict((a["artifact_id"], a) for a in self.tables["artifacts"])
        entries = {(e["artifact_id"], e["tool"]): e for e in self.tables["tool_entries"]}
        blocking = set((f["artifact_id"], f["tool"]) for f in self.tables["findings"]
                       if f["kind"] == "reported_blocking" and f["family"] in ("memory", "null_deref", "uninitialized"))
        table = Counter()
        for aid in arts:
            a, b = entries[(aid, "gcc_analyzer")], entries[(aid, "cppcheck")]
            if a["state"] == "COMPLETED" and b["state"] == "COMPLETED":
                table[((aid, "gcc_analyzer") in blocking, (aid, "cppcheck") in blocking)] += 1
        est = self.get("F06", "GENERATED", "composite", pair="gcc_analyzer+cppcheck",
                       **{"class": "memory+null_deref+uninitialized"})
        self.assertEqual((est["n11"], est["n10"], est["n01"], est["n00"]),
                         (table[(True, True)], table[(True, False)], table[(False, True)], table[(False, False)]))
        self.assertEqual(est["kappa"], stats.cohens_kappa(est["n11"], est["n10"], est["n01"], est["n00"]))
        omp = self.get("F06", "GENERATED", "composite", pair="tsan+llov", **{"class": "race"})
        omp_ids = [aid for aid, a in arts.items() if a["execution_model"] == "omp"
                   and entries[(aid, "tsan")]["state"] == "COMPLETED"
                   and entries[(aid, "llov")]["state"] == "COMPLETED"]
        self.assertEqual(omp["denominator"], len(omp_ids))

    def test_primary_family_and_holm(self):
        primary = [e for e in self.estimates if e["p_value"] is not None]
        self.assertEqual(len(primary), 12)
        self.assertEqual(set(e["metric_id"] for e in primary), {"R04", "R05"})
        self.assertTrue(all(e["block"] == "composite" and e["population"] == "FINAL" for e in primary))
        self.assertEqual(sorted(set(json.dumps(e["strata"]) for e in primary)),
                         sorted(json.dumps(e["strata"]) for e in primary))
        for e in primary:
            self.assertIsNotNone(e["p_holm"])
            self.assertIsInstance(e["reject_holm"], bool)
            self.assertGreaterEqual(e["p_holm"], e["p_value"])
            self.assertEqual(e["replicates"], PRIMARY)
            self.assertEqual(set(e["strata"]) - {"endpoint", "variant", "comparison"}, set())
        ordered = sorted(primary, key=lambda e: e["p_value"])
        self.assertEqual([e["p_holm"] for e in ordered], sorted(e["p_holm"] for e in ordered))
        others = [e for e in self.estimates if e["p_value"] is None]
        self.assertTrue(all(e["p_holm"] is None and e["reject_holm"] is None for e in others))
        rerun = metrics.compute_primary(core.Dataset(copy.deepcopy(self.tables)), self.methodology, PRIMARY,
                                        exploratory=True)
        self.assertEqual(json.dumps(rerun), json.dumps(sorted(primary, key=metrics.sort_key)))
        descriptive = self.get("R04", "FINAL", "pilot", endpoint="Q06", variant="static_feedback")
        self.assertEqual(descriptive["replicates"], DESCRIPTIVE)
        self.assertIsNone(descriptive["p_value"])

    def test_trajectory_metrics(self):
        trajs = self.tables["trajectories"]
        for v in core.VARIANTS:
            mine = [t for t in trajs if t["variant"] == v]
            total = 0
            for status in core.TERMINAL_STATUSES:
                r06 = self.get("R06", "TRAJECTORIES", "composite", variant=v, status=status)
                self.assertEqual(r06["numerator"], sum(t["terminal_status"] == status for t in mine))
                self.assertEqual(r06["denominator"], len(mine))
                total += r06["numerator"]
                split = sum(self.get("R06", "TRAJECTORIES", "composite", variant=v, status=status,
                                     iteration=i)["numerator"] for i in range(3))
                self.assertEqual(split, r06["numerator"])
            self.assertEqual(total, len(mine))
            r10 = self.get("R10", "TRAJECTORIES", "composite", variant=v)
            self.assertEqual(r10["numerator"], sum(t["final_iteration"] for t in mine))
            r09 = self.get("R09", "TRAJECTORIES", "composite", variant=v)
            self.assertEqual(r09["numerator"], sum(t["final_iteration"] >= 1 for t in mine))
            c01 = self.get("C01", "REPAIR_CANDIDATES", "composite", variant=v, quantity="records_per_trajectory")
            self.assertEqual(c01["numerator"], sum(t["final_iteration"] for t in mine))
            rounds = self.get("C01", "REPAIR_CANDIDATES", "composite", variant=v,
                              quantity="request_rounds_per_trajectory")
            self.assertEqual(rounds["numerator"], sum(t["request_rounds"] for t in mine))

    def test_effort_tokens_latency_runtime(self):
        gens = OrderedDict((g["artifact_id"], g) for g in self.tables["generations"])
        arts = OrderedDict((a["artifact_id"], a) for a in self.tables["artifacts"])
        base = [gens[aid] for aid, a in arts.items() if a["iteration"] == 0]
        c02 = self.get("C02", "BASE", "composite", quantity="reasoning_tokens")
        reported = [g["reasoning_tokens"] for g in base if g["reasoning_tokens"] is not None]
        self.assertEqual((c02["numerator"], c02["denominator"], c02["generations"]),
                         (sum(reported), len(reported), len(base)))
        self.assertAlmostEqual(c02["coverage"], len(reported) / float(len(base)))
        v = "combined_feedback"
        repair = [gens[aid] for aid, a in arts.items() if a["iteration"] > 0 and a["variant"] == v]
        c03 = self.get("C03", "REPAIR_CANDIDATES", "composite", variant=v)
        self.assertEqual(c03["value"], stats.median([g["duration_seconds"] for g in repair]))
        self.assertEqual(c03["n"], len(repair))
        improved = self._paired_truth("composite", v)["improved"]
        tokens = sum(g["output_tokens"] for g in repair)
        c05 = self.get("C05", "FINAL", "composite", variant=v, quantity="per_1M_output_tokens")
        self.assertAlmostEqual(c05["value"], improved * 1e6 / tokens)
        ran = [e for e in self.tables["tool_entries"] if e["tool"] == "infer" and e["ran"]]
        c04 = self.get("C04", "GENERATED", "composite", tool="infer", outlier_rule="all")
        self.assertEqual(c04["timeouts"], sum(e["state"] == "TIMEOUT" for e in ran))
        self.assertEqual(c04["n"], sum(e["state"] != "TIMEOUT" for e in ran))
        self.assertEqual(c04["value"], stats.median([e["duration_seconds"] for e in ran if e["state"] != "TIMEOUT"]))
        self.assertGreater(c04["timeouts"], 0)
        self.assertEqual(c04["ran_entries"], len(ran))                  # the TIMEOUT share is reported directly
        self.assertAlmostEqual(c04["timeout_share"], c04["timeouts"] / float(len(ran)))
        rule = self.get("C04", "GENERATED", "composite", tool="infer", outlier_rule="excluding_above_threshold")
        self.assertEqual((rule["ran_entries"], rule["timeout_share"]), (c04["ran_entries"], c04["timeout_share"]))
        c02 = self.get("C02", "BASE", "composite", quantity="output_tokens")
        self.assertEqual((c02["denominator"], c02["coverage"]), (len(base), 1.0))

    def test_heldout_g01_g02(self):
        v = "static_feedback"
        g02 = self.get("G02", "STEP", "composite", endpoint="Q06", variant=v, step=1)
        q06 = self.get("Q06", "STEP", "composite", variant=v, step=1)
        for key in ("numerator", "denominator", "value", "ci_low", "ci_high"):
            self.assertEqual(g02[key], q06[key])
        rate = self.get("G01", "FINAL", "composite", variant=v)
        diff = self.get("G01", "FINAL", "composite", variant=v, comparison="G01-E05(BASE)")
        ref = self.get("E05", "BASE", "composite")
        self.assertEqual((diff["reference_numerator"], diff["reference_denominator"]),
                         (ref["numerator"], ref["denominator"]))
        if rate["value"] is not None and ref["value"] is not None:
            self.assertAlmostEqual(diff["value"], rate["value"] - ref["value"])

    def test_sensitivity_sa1_drops_bl01(self):
        kept = [a for a in self.tables["artifacts"] if a["iteration"] == 0 and a["benchmark"] != core.BL01_BENCHMARK]
        sa1 = self.get("Q06", "BASE", "composite", sensitivity="SA1")
        self.assertEqual(sa1["denominator"], len(kept))
        self.assertEqual(sa1["numerator"], sum(a["correctness_verdict"] == "pass" for a in kept))
        full = self.get("R04", "FINAL", "full_ext", endpoint="Q06", variant="test_feedback", sensitivity="SA1")
        main = self.get("R04", "FINAL", "full_ext", endpoint="Q06", variant="test_feedback")
        self.assertEqual((full["numerator"], full["denominator"]), (main["numerator"], main["denominator"]))

    def test_sa1_resamples_the_remaining_benchmarks(self):
        """Regression: SA1 is a re-analysis without BL-01, so its interval comes
        from a bootstrap over the remaining clusters (same seed / replicates),
        not from the main bootstrap with an empty BL-01 cluster."""
        kept = OrderedDict((c, s) for c, s in self.co["clusters"].items() if c != core.BL01_BENCHMARK)
        self.assertEqual(len(kept), len(self.co["clusters"]) - 1)
        boot = stats.ClusterBootstrap(kept, DESCRIPTIVE, self.methodology["statistics"]["bootstrap"]["seed"], 0.95)
        checked = 0
        for v in core.VARIANTS:
            per = OrderedDict()
            for cid, cell in self.co["cells"].items():
                if cell["block"] != "full_ext":
                    continue
                d = int(self.co["final"][v][cid]["correctness_verdict"] == "pass") - int(
                    self.co["base"][cid]["correctness_verdict"] == "pass")
                pair = per.setdefault(cell["benchmark"], [0, 0])
                pair[0] += d
                pair[1] += 1
            truth = boot.difference(OrderedDict((c, tuple(p)) for c, p in per.items()))
            est = self.get("R04", "FINAL", "full_ext", endpoint="Q06", variant=v, sensitivity="SA1")
            self.assertEqual((est["value"], est["ci_low"], est["ci_high"]), (truth["value"], truth["ci_low"],
                                                                             truth["ci_high"]))
            self.assertIsNotNone(est["ci_low"])
            checked += 1
        self.assertEqual(checked, 3)
        # without BL-01 the fixture's pilot stratum is a single benchmark: never resampled -> no interval
        composite = self.get("R04", "FINAL", "composite", endpoint="Q06", variant="static_feedback", sensitivity="SA1")
        self.assertIsNone(composite["ci_low"])
        self.assertIn("single-cluster bootstrap stratum pilot", composite["note"])

    def test_single_cluster_domains_have_no_interval(self):
        """Regression: every family of this fixture has one benchmark per block,
        so no per-block per-family estimate may carry an interval; a composite
        family with a benchmark in each block keeps one."""
        per_family = [e for e in self.estimates if "family" in e["strata"] and e["block"] != "composite"
                      and e["metric_id"] != "F05" and e["value"] is not None]
        self.assertGreater(len(per_family), 100)
        for e in per_family:
            self.assertIsNone(e["ci_method"], metrics.sort_key(e))
            self.assertIsNone(e["ci_low"])
        flagged = [e for e in per_family if e["note"] and "CI not estimable" in e["note"]]
        self.assertGreater(len(flagged), 50)
        dense = self.get("Q06", "BASE", "composite", family="dense_la")
        self.assertEqual(dense["ci_method"], stats.CI_METHOD)
        sort = self.get("Q06", "BASE", "composite", family="sort")                  # full_ext only
        self.assertIsNone(sort["ci_method"])
        for e in self.estimates:                                                 # no zero-width one-cluster CI
            if e["ci_method"] is not None:
                self.assertNotIn("CI not estimable", e["note"] or "")

    # ---- post-freeze addendum_1 ------------------------------------------------------------------------

    def descriptive(self):
        seed = self.methodology["statistics"]["bootstrap"]["seed"]
        return stats.ClusterBootstrap(self.raw.clusters, DESCRIPTIVE, seed, 0.95)

    def test_new_estimate_fields(self):
        ids = set(core.addendum_metric_ids(self.addendum))
        degenerate = 0
        for e in self.estimates:
            key = metrics.sort_key(e)
            self.assertEqual(e["post_freeze"], e["metric_id"] in ids, key)
            if e["post_freeze"]:
                self.assertTrue(e["note"].startswith(POST_FREEZE), key)
                self.assertIsNone(e["p_value"])
                self.assertIsNone(e["p_holm"])
            if e["ci_low"] is None:
                self.assertIsNone(e["ci_high"])
                self.assertIsNone(e["ci_degenerate"], key)
            else:
                self.assertEqual(e["ci_degenerate"], e["ci_low"] == e["ci_high"], key)
            self.assertEqual(DEGENERATE in (e["note"] or ""), bool(e["ci_degenerate"]), key)
            degenerate += bool(e["ci_degenerate"])
            if e["p_value"] is None:
                self.assertEqual((e["p_resolution"], e["p_holm_resolution"]), (None, None), key)
        self.assertGreater(degenerate, 10)
        primary = [e for e in self.estimates if e["p_value"] is not None]
        self.assertEqual(len(primary), 12)
        running = 0.0
        ordered = sorted(primary, key=lambda e: (e["p_value"], metrics.sort_key(e)))
        for rank, e in enumerate(ordered, 1):
            self.assertEqual(e["p_resolution"], 2.0 / PRIMARY)
            running = max(running, (12 - rank + 1) * e["p_resolution"])
            self.assertEqual(e["p_holm_resolution"], running)
        self.assertEqual(ordered[0]["p_holm_resolution"], 12 * 2.0 / PRIMARY)

    def test_x01_auto_closed_sensitivity(self):
        boot = self.descriptive()
        closed = [cid for cid in self.raw.cells if any(a["clean_auto_closed"] for a in self.raw.on_trajectories(cid))]
        self.assertGreater(len(closed), 3)
        intermediate = [cid for cid in closed if not self.raw.base[cid]["clean_auto_closed"] and not any(
            self.raw.final(cid, v)["clean_auto_closed"] for v in core.VARIANTS)]
        self.assertGreater(len(intermediate), 0)          # excluded only through an intermediate iteration
        checked = 0
        for block in ("pilot", "full_ext", "composite"):
            cells = sum(1 for c in self.raw.cells.values() if self.raw.in_block(c, block))
            for endpoint in ("Q06", "E02"):
                shapes = [(dict(variant=v), dict(variant=v)) for v in core.VARIANTS]
                shapes += [(dict(comparison="%s-%s" % pair), dict(comparison=pair)) for pair in metrics.COMPARISONS]
                for strata, args in shapes:
                    e = self.get("X01", "FINAL", block, endpoint=endpoint, **strata)
                    num, den, excluded, per = self.raw.x01(block, endpoint, **args)
                    self.assertEqual((e["numerator"], e["denominator"], e["excluded"]), (num, den, excluded))
                    self.assertEqual(den + excluded, cells)
                    truth = boot.ratio(per)
                    self.assertEqual((e["value"], e["ci_low"], e["ci_high"]),
                                     (truth["value"], truth["ci_low"], truth["ci_high"]))
                    self.assertEqual(e["statistic"], "difference")
                    self.assertIsNone(e["p_value"])
                    self.assertIn("excluded: %d base cell(s)" % excluded, e["note"])
                    if block == "composite":
                        self.assertEqual(e["ci_method"], stats.CI_METHOD)
                    checked += 1
        self.assertEqual(checked, 3 * 2 * 6)
        self.assertEqual(len([e for e in self.estimates if e["metric_id"] == "X01"]), checked)

    def test_x02_tool_verdict_reading(self):
        raw = self.raw
        pops = [("BASE", {}, [raw.base[c] for c in raw.cells])]
        pops += [("FINAL", {"variant": v}, [raw.final(c, v) for c in raw.cells]) for v in core.VARIANTS]
        only_total = 0
        for population, fixed, arts in pops:
            for block in ("pilot", "full_ext", "composite"):
                for em in (None,) + core.EXECUTION_MODELS:
                    if em is not None and population != "BASE":
                        continue
                    mine = [a for a in arts if raw.in_block(a, block) and (em is None or a["execution_model"] == em)]
                    strata = dict(fixed, **({"execution_model": em} if em else {}))
                    for state in core.THREE_STATE:
                        e = self.get("X02", population, block, state=state, **strata)
                        num = sum(1 for a in mine if raw.static_state(a["artifact_id"], True) == state)
                        self.assertEqual((e["numerator"], e["denominator"]), (num, len(mine)))
                        if state == "DIRTY":
                            only = sum(1 for a in mine if a["static_three_state"] == "DIRTY"
                                       and raw.static_state(a["artifact_id"], True) != "DIRTY")
                            self.assertEqual(e["dirty_only_under_frozen_rule"], only)
                            only_total += only
                            if block == "composite" and em is None:
                                self.assertEqual(e["ci_method"], stats.CI_METHOD)
                        else:
                            self.assertNotIn("dirty_only_under_frozen_rule", e)
                            self.assertIsNone(e["ci_method"])
        self.assertGreater(only_total, 0)          # the fixture has findings recorded under gap-state entries
        self.assertEqual(len([e for e in self.estimates if e["metric_id"] == "X02"]), 3 * (3 + 3 * 3 + 3 * 3))

    def test_x03_dirty_composition(self):
        raw = self.raw
        base = [raw.base[c] for c in raw.cells]
        tools = core.STATIC_ANALYSIS_TOOLS
        top = int(re.search(r"the ([0-9]+) check ids", [m for m in self.addendum["metrics"] if m["id"] == "X03"][0]
                            ["meaning"]).group(1))
        composite = Counter()
        for (aid, tool, check), n in raw.checks.items():
            if tool in tools and raw.arts[aid]["iteration"] == 0:
                composite[(tool, check)] += n
        selected = OrderedDict((t, [c for c, _ in sorted(((c, n) for (tt, c), n in composite.items() if tt == t),
                                                        key=lambda x: (-x[1], x[0]))[:top]]) for t in tools)
        self.assertGreater(sum(len(v) for v in selected.values()), 3)
        for block in ("pilot", "full_ext", "composite"):
            mine = [a for a in base if raw.in_block(a, block)]
            dirty = [a for a in mine if a["static_three_state"] == "DIRTY"]
            for t in tools:
                only = sum(1 for a in dirty if [x for x in tools if raw.blocking[(a["artifact_id"], x)]] == [t])
                e = self.get("X03", "BASE", block, tool=t, quantity="dirty_only_via_tool")
                self.assertEqual((e["numerator"], e["denominator"]), (only, len(dirty)))
                applicable = [a for a in mine if raw.entries[a["artifact_id"]][t]["applicable"]]
                for c in selected[t]:
                    count = self.get("X03", "BASE", block, tool=t, check_id=c, quantity="blocking_findings")
                    self.assertEqual(count["numerator"], sum(raw.checks[(a["artifact_id"], t, c)] for a in mine))
                    self.assertEqual((count["denominator"], count["value"], count["statistic"]), (None, None, "count"))
                    share = self.get("X03", "BASE", block, tool=t, check_id=c, quantity="artifacts_with_check")
                    self.assertEqual((share["numerator"], share["denominator"]),
                                     (sum(1 for a in mine if raw.checks[(a["artifact_id"], t, c)]), len(applicable)))
            rows = [e for e in self.estimates if e["metric_id"] == "X03" and e["block"] == block]
            self.assertEqual(len(rows), len(tools) + 2 * sum(len(v) for v in selected.values()))
            self.assertTrue(all(e["ci_method"] is None for e in rows))

    def test_x04_statically_clean_but_incorrect(self):
        raw = self.raw
        pops = [("BASE", {}, [raw.base[c] for c in raw.cells])]
        pops += [("FINAL", {"variant": v}, [raw.final(c, v) for c in raw.cells]) for v in core.VARIANTS]
        for population, fixed, arts in pops:
            for block in ("pilot", "full_ext", "composite"):
                failing = [a for a in arts if raw.in_block(a, block)
                           and a["correctness_verdict"] not in ("pass", "baseline_incompatible")]
                for state in ("CLEAN_COMPLETE", "NO_FINDING_INCOMPLETE"):
                    e = self.get("X04", population, block, state=state, **fixed)
                    num = sum(1 for a in failing if raw.static_state(a["artifact_id"]) == state)
                    self.assertEqual((e["numerator"], e["denominator"]), (num, len(failing)))
                    if block == "composite":
                        self.assertEqual(e["ci_method"], stats.CI_METHOD)
                    # regression: only CLEAN_COMPLETE is 'statically clean' (a gap without a finding never is)
                    self.assertIn("F01 is %s" % state, e["note"])
                    if state == "CLEAN_COMPLETE":
                        self.assertIn("statically clean", e["note"])
                    else:
                        self.assertNotIn("statically clean", e["note"])
                        self.assertIn("NOT clean", e["note"])
                with self.assertRaises(KeyError):
                    self.get("X04", population, block, state="DIRTY", **fixed)

    def test_x05_iterations_to_clean(self):
        for block in ("pilot", "full_ext", "composite"):
            for v in core.VARIANTS:
                clean = [t for t in self.tables["trajectories"] if t["variant"] == v and self.raw.in_block(t, block)
                         and t["terminal_status"] in ("stopped_clean", "stopped_tests_pass")]
                self.assertGreater(len(clean), 0)
                mean = self.get("X05", "TRAJECTORIES", block, variant=v)
                self.assertEqual((mean["numerator"], mean["denominator"], mean["statistic"]),
                                 (sum(t["final_iteration"] for t in clean), len(clean), "mean"))
                self.assertAlmostEqual(mean["value"], mean["numerator"] / float(len(clean)))
                total = 0
                for k in range(core.MAX_ITERATIONS + 1):
                    e = self.get("X05", "TRAJECTORIES", block, variant=v, iteration=k)
                    self.assertEqual((e["numerator"], e["denominator"]),
                                     (sum(1 for t in clean if t["final_iteration"] == k), len(clean)))
                    total += e["numerator"]
                self.assertEqual(total, len(clean))

    def test_x06_joint_transitions(self):
        raw = self.raw
        labels = lambda states: ["%s->%s" % (x, y) for x in states for y in states]  # noqa: E731
        q_labels, h_labels = labels(("pass", "not_pass")), labels(("all_pass", "not_all_pass"))
        state = lambda endpoint, a: (("pass" if raw.y(endpoint, a) else "not_pass") if endpoint == "Q06"  # noqa
                                     else ("all_pass" if raw.y(endpoint, a) else "not_all_pass"))
        for block in ("pilot", "full_ext", "composite"):
            cohort = [c for c, cell in raw.cells.items() if raw.in_block(cell, block)
                      and raw.paired("Q06", c) and raw.paired("E02", c)]
            self.assertEqual(len(cohort), sum(1 for c, cell in raw.cells.items() if raw.in_block(cell, block)
                                              and raw.base[c]["enh_valid"] > 0))
            for v in core.VARIANTS:
                truth = Counter()
                for c in cohort:
                    b, f = raw.base[c], raw.final(c, v)
                    truth[("%s->%s" % (state("Q06", b), state("Q06", f)),
                           "%s->%s" % (state("E02", b), state("E02", f)))] += 1
                total = 0
                for q in q_labels:
                    for h in h_labels:
                        e = self.get("X06", "FINAL", block, variant=v, transition=q, heldout_transition=h)
                        self.assertEqual((e["numerator"], e["denominator"]), (truth[(q, h)], len(cohort)))
                        total += e["numerator"]
                self.assertEqual(total, len(cohort))
                # the E02 margin is R01 E02 (the same cohort: the fixture has no baseline_incompatible artifact)
                for h in h_labels:
                    margin = sum(self.get("X06", "FINAL", block, variant=v, transition=q, heldout_transition=h)
                                 ["numerator"] for q in q_labels)
                    self.assertEqual(margin, self.get("R01", "FINAL", block, endpoint="E02", variant=v,
                                                      transition=h)["numerator"])
        self.assertEqual(len([e for e in self.estimates if e["metric_id"] == "X06"]), 3 * 3 * 16)


class HandComputedTest(unittest.TestCase):
    """One model, two benchmarks per block (pilot: the BL-01 benchmark and
    an fft benchmark; full_ext: a dense_la and a sort benchmark), three
    execution models; every benchmark follows the same verdict plan, so each
    composite count is 4 x the per-benchmark count (3 cells per benchmark).
    Every Q06 number below is computed by hand. Two benchmarks per block
    because a single-cluster bootstrap stratum is never resampled (no
    interval, no p-value - the primary family would refuse)."""

    PILOT = (core.BL01_BENCHMARK, "fft/05_fft_one")
    FULL = ("dense_la/01_dense_la_two", "sort/40_sort_four")

    BASE = {"serial": "pass", "omp": "validation_failed", "mpi": "build_failed"}
    STEPS = {("static_feedback", 1): {"serial": "pass", "omp": "pass", "mpi": "validation_failed"},
             ("combined_feedback", 1): {"serial": "validation_failed", "omp": "pass", "mpi": "runtime_error"},
             ("combined_feedback", 2): {"serial": "validation_failed", "omp": "pass", "mpi": "pass"}}
    PLAN = {"static_feedback": (1, "stopped_tests_pass"), "test_feedback": (0, "stopped_clean"),
            "combined_feedback": (2, "stopped_budget")}

    @classmethod
    def setUpClass(cls):
        def verdict(a, rng):
            if a["iteration"] == 0:
                return cls.BASE[a["execution_model"]]
            return cls.STEPS[(a["variant"], a["iteration"])][a["execution_model"]]
        cls.tables = synthetic_tables(pilot=cls.PILOT, full_ext=cls.FULL,
                                      models=("model_a",), final_plan=lambda c, v, r: cls.PLAN[v],
                                      verdict_plan=verdict, seed=9)
        cls.estimates = metrics.compute(core.Dataset(copy.deepcopy(cls.tables)), core.load_methodology(), 50, 20,
                                        exploratory=True)
        cls.by = index(cls.estimates)

    def get(self, metric, population, block, **strata):
        return self.by[(metric, population, block, strata_json(**strata))]

    def test_counts(self):
        c = "composite"
        self.assertEqual(self.get("Q06", "BASE", c)["numerator"], 4)
        self.assertEqual(self.get("Q06", "BASE", c)["denominator"], 12)
        self.assertEqual(self.get("Q06", "FINAL", c, variant="static_feedback")["numerator"], 8)
        self.assertEqual(self.get("Q06", "FINAL", c, variant="test_feedback")["numerator"], 4)
        self.assertEqual(self.get("Q06", "FINAL", c, variant="combined_feedback")["numerator"], 8)
        self.assertEqual(self.get("Q06", "STEP", c, variant="combined_feedback", step=1)["numerator"], 4)
        r02 = self.get("R02", "FINAL", c, endpoint="Q06", variant="static_feedback")
        self.assertEqual((r02["numerator"], r02["denominator"], r02["value"]), (4, 8, 0.5))
        r02 = self.get("R02", "FINAL", c, endpoint="Q06", variant="test_feedback")
        self.assertEqual((r02["numerator"], r02["denominator"]), (0, 8))            # stopped_clean != success
        r02 = self.get("R02", "FINAL", c, endpoint="Q06", variant="combined_feedback")
        self.assertEqual((r02["numerator"], r02["denominator"]), (8, 8))
        r03 = self.get("R03", "FINAL", c, endpoint="Q06", variant="combined_feedback")
        self.assertEqual((r03["numerator"], r03["denominator"]), (4, 4))
        for v, expected in (("static_feedback", 4), ("test_feedback", 0), ("combined_feedback", 4)):
            r04 = self.get("R04", "FINAL", c, endpoint="Q06", variant=v)
            self.assertEqual((r04["numerator"], r04["denominator"]), (expected, 12))
        for (v1, v2), expected in ((("static_feedback", "test_feedback"), 4),
                                   (("static_feedback", "combined_feedback"), 0),
                                   (("test_feedback", "combined_feedback"), -4)):
            r05 = self.get("R05", "FINAL", c, endpoint="Q06", comparison="%s-%s" % (v1, v2))
            self.assertEqual(r05["numerator"], expected)
            self.assertAlmostEqual(r05["value"], expected / 12.0)
        moves = OrderedDict([("pass->pass", 0), ("pass->not_pass", 4), ("not_pass->pass", 8),
                             ("not_pass->not_pass", 0)])
        for transition, n in moves.items():
            self.assertEqual(self.get("R01", "FINAL", c, endpoint="Q06", variant="combined_feedback",
                                      transition=transition)["numerator"], n)
        r06 = self.get("R06", "TRAJECTORIES", c, variant="test_feedback", status="stopped_clean")
        self.assertEqual((r06["numerator"], r06["denominator"]), (12, 12))
        self.assertEqual(self.get("R10", "TRAJECTORIES", c, variant="combined_feedback")["value"], 2.0)
        sa1 = self.get("Q06", "BASE", c, sensitivity="SA1")                          # 3 benchmarks remain
        self.assertEqual((sa1["numerator"], sa1["denominator"]), (3, 9))
        sa1 = self.get("R04", "FINAL", c, endpoint="Q06", variant="static_feedback", sensitivity="SA1")
        self.assertEqual((sa1["numerator"], sa1["denominator"]), (3, 9))
        q07 = self.get("Q07", "BASE", c)
        self.assertEqual((q07["numerator"], q07["denominator"]), (4, 8))          # mpi did not build
        q08 = self.get("Q08", "BASE", c, verdict="build_failed")
        self.assertEqual((q08["numerator"], q08["denominator"]), (4, 12))
        pilot = self.get("Q06", "BASE", "pilot")
        self.assertEqual((pilot["numerator"], pilot["denominator"]), (2, 6))
        # both pilot clusters show 1/3: a data-driven zero width over 2 resampled clusters is a real interval,
        # kept but flagged zero-width (addendum_1 ci_degenerate)
        self.assertEqual((pilot["ci_low"], pilot["ci_high"], pilot["ci_method"]), (1 / 3.0, 1 / 3.0, stats.CI_METHOD))
        self.assertTrue(pilot["ci_degenerate"])
        self.assertTrue(pilot["note"].endswith(DEGENERATE))

    def test_single_cluster_domain_has_no_interval(self):
        """Regression: pilot family dense_la is ONE benchmark (BL-01); its rate
        is invariant to the cluster's bootstrap weight, so no interval (the old
        code reported a zero-width 'cluster_bootstrap_percentile' CI)."""
        for metric, population, endpoint in (("Q06", "BASE", None), ("Q06", "FINAL", None),
                                             ("E01", "ENH_PAIRS(BASE)", None), ("R04", "FINAL", "Q06")):
            strata = {"family": "dense_la"}
            if population == "FINAL":
                strata["variant"] = "static_feedback"
            if endpoint:
                strata["endpoint"] = endpoint
            est = self.get(metric, population, "pilot", **strata)
            self.assertIsNotNone(est["value"])
            self.assertEqual((est["ci_low"], est["ci_high"], est["ci_method"], est["replicates"]),
                             (None, None, None, None))
            self.assertIn("CI not estimable: the estimate rests on 1 benchmark cluster", est["note"])
        dense = self.get("Q06", "BASE", "pilot", family="dense_la")
        self.assertEqual((dense["numerator"], dense["denominator"]), (1, 3))
        fft = self.get("Q06", "BASE", "composite", family="fft")                    # fft: pilot only
        self.assertIsNone(fft["ci_method"])
        two = self.get("Q06", "BASE", "composite", family="dense_la")               # one cluster per block
        self.assertEqual(two["ci_method"], stats.CI_METHOD)
        self.assertIn("only 1 supporting benchmark cluster in bootstrap stratum full_ext, pilot", two["note"])

    def test_primary_family_is_complete(self):
        primary = [e for e in self.estimates if e["p_value"] is not None]
        self.assertEqual(len(primary), 12)
        self.assertTrue(all(e["ci_method"] == stats.CI_METHOD and e["reject_holm"] is not None for e in primary))
        self.assertTrue(all("EXPLORATORY: 50 bootstrap replicates (methodology 10000)" in e["note"]
                            for e in primary))


class AddendumHandTest(unittest.TestCase):
    """X01-X06 by hand. The HandComputedTest plan (one model; pilot: BL-01 +
    fft/05, full_ext: dense_la/01 + sort/40; 3 execution models -> 12 cells;
    static_feedback stops at 1, test_feedback at 0, combined_feedback at 2)
    plus: no gates, enhanced status pass iff the test verdict passes except
    one failing spec of the combined_feedback iteration-2 mpi answer (Q06
    repaired, held-out not), a fixed static tool plan and auto-closed answers
    in three cells (one only at an intermediate iteration).

    Per cell (serial / omp / mpi), BASE verdicts pass / validation_failed /
    build_failed; FINAL static pass / pass / validation_failed, test = BASE,
    combined validation_failed / pass / pass. Static tools at BASE: serial
    clang_tidy COMPLETED + 1 blocking (narrowing), omp clang_tidy NOT_ANALYZED
    + 1 blocking (swappable) -> frozen DIRTY, tool-verdict reading
    NO_FINDING_INCOMPLETE; mpi clang_tidy (narrowing) + infer 2 x
    INTEGER_OVERFLOW_L2 + gcc_analyzer 1 x '-Wanalyzer-b' and 1 x
    '-Wanalyzer-a' (all COMPLETED). Candidates: no findings; static_feedback
    it1 omp gcc_analyzer PARTIAL, combined_feedback it2 serial gcc_analyzer
    TIMEOUT (NO_FINDING_INCOMPLETE), the others CLEAN_COMPLETE."""

    CLOSED = {("fft/05_fft_one", "omp", "static_feedback", 1), ("sort/40_sort_four", "serial", "", 0),
              ("dense_la/01_dense_la_two", "mpi", "combined_feedback", 1)}
    BASE_TOOLS = {
        ("serial", "clang_tidy"): ("COMPLETED",
                                   [("arithmetic", "reported_blocking", "bugprone-narrowing-conversions")]),
        ("omp", "clang_tidy"): ("NOT_ANALYZED",
                                [("other", "reported_blocking", "bugprone-easily-swappable-parameters")]),
        ("mpi", "clang_tidy"): ("COMPLETED", [("arithmetic", "reported_blocking", "bugprone-narrowing-conversions")]),
        ("mpi", "infer"): ("COMPLETED", [("arithmetic", "reported_blocking", "INTEGER_OVERFLOW_L2")] * 2),
        ("mpi", "gcc_analyzer"): ("COMPLETED", [("memory", "reported_blocking", "-Wanalyzer-b"),
                                                ("memory", "reported_blocking", "-Wanalyzer-a")]),
    }
    CANDIDATE_TOOLS = {("static_feedback", 1, "omp", "gcc_analyzer"): ("PARTIAL", []),
                       ("combined_feedback", 2, "serial", "gcc_analyzer"): ("TIMEOUT", [])}

    @classmethod
    def tables_for(cls):
        hand = HandComputedTest

        def verdict(a, rng):
            if a["iteration"] == 0:
                return hand.BASE[a["execution_model"]]
            return hand.STEPS[(a["variant"], a["iteration"])][a["execution_model"]]

        def tools(a, tool, rng):
            if tool == "compiler":
                build = a["correctness_verdict"] == "build_failed"
                return "COMPLETED", [("build", "reported_blocking", "compile-error")] if build else []
            if a["iteration"] == 0:
                return cls.BASE_TOOLS.get((a["execution_model"], tool), ("COMPLETED", []))
            return cls.CANDIDATE_TOOLS.get((a["variant"], a["iteration"], a["execution_model"], tool),
                                           ("COMPLETED", []))

        def enhanced(a, key, rng):
            if a["correctness_verdict"] == "build_failed":
                return "build_failed"
            if (a["variant"], a["iteration"], a["execution_model"]) == ("combined_feedback", 2, "mpi") and \
                    json.loads(key)["size"] == 0:
                return "fail"
            return "pass" if a["correctness_verdict"] == "pass" else "fail"

        def clean(a):
            flags = OrderedDict((f, False) for f in core.CLEANING_FLAGS)
            flags["auto_closed"] = (a["benchmark"], a["execution_model"], a["variant"], a["iteration"]) in cls.CLOSED
            return flags
        return synthetic_tables(pilot=hand.PILOT, full_ext=hand.FULL, models=("model_a",),
                                final_plan=lambda c, v, r: hand.PLAN[v], verdict_plan=verdict, tool_plan=tools,
                                enh_plan=enhanced, clean_plan=clean, gate_share=0.0, seed=9)

    @classmethod
    def setUpClass(cls):
        cls.methodology = core.load_methodology()
        cls.addendum = core.load_addendum(methodology=cls.methodology)
        cls.tables = cls.tables_for()
        cls.estimates = metrics.compute(core.Dataset(copy.deepcopy(cls.tables)), cls.methodology, 50, 20,
                                        exploratory=True, addendum=cls.addendum)
        cls.by = index(cls.estimates)

    def get(self, metric, population, block, **strata):
        return self.by[(metric, population, block, strata_json(**strata))]

    def nd(self, metric, population, block, **strata):
        e = self.get(metric, population, block, **strata)
        return e["numerator"], e["denominator"]

    def test_tied_zero_holm_resolution(self):
        """Every benchmark follows the same plan (enhanced statuses included),
        so every replicate equals the point estimate: p = 0 for the 7 non-zero
        differences, p = 1 for the 5 zero ones (hand count below). The Holm-adjusted p of the tied zeros is
        0, its resolution 12 * 2 / B (B = 50 here), never 2 / B."""
        primary = [e for e in self.estimates if e["p_value"] is not None]
        zero = sorted((e for e in primary if e["p_value"] == 0.0), key=metrics.sort_key)
        labels = sorted((e["metric_id"], e["strata"]["endpoint"], e["strata"].get("variant") or
                         e["strata"]["comparison"]) for e in zero)
        self.assertEqual(labels, sorted([
            ("R04", "Q06", "static_feedback"), ("R04", "Q06", "combined_feedback"),
            ("R05", "Q06", "static_feedback-test_feedback"), ("R05", "Q06", "test_feedback-combined_feedback"),
            ("R04", "E02", "static_feedback"), ("R05", "E02", "static_feedback-test_feedback"),
            ("R05", "E02", "static_feedback-combined_feedback")]))
        for e in primary:
            self.assertEqual(e["p_resolution"], 2.0 / 50)
            self.assertEqual(e["p_holm_resolution"], 12 * (2.0 / 50))       # running maximum from rank 1
            self.assertTrue(e["ci_degenerate"])                           # identical clusters: zero width
            self.assertIn(DEGENERATE, e["note"])
            self.assertEqual(e["p_holm"], 0.0 if e["p_value"] == 0.0 else 1.0)
        self.assertEqual(len(zero), 7)
        self.assertTrue(all(e["reject_holm"] for e in zero))
        non_primary = [e for e in self.estimates if e["p_value"] is None]
        self.assertTrue(all(e["p_resolution"] is None and e["p_holm_resolution"] is None for e in non_primary))

    def test_x01(self):
        c = "composite"
        for v, n in (("static_feedback", 3), ("test_feedback", 0), ("combined_feedback", 3)):
            e = self.get("X01", "FINAL", c, endpoint="Q06", variant=v)
            self.assertEqual((e["numerator"], e["denominator"], e["excluded"]), (n, 9, 3))
            self.assertAlmostEqual(e["value"], n / 9.0)
        self.assertEqual(self.nd("X01", "FINAL", "pilot", endpoint="Q06", variant="static_feedback"), (1, 5))
        self.assertEqual(self.nd("X01", "FINAL", "full_ext", endpoint="Q06", variant="static_feedback"), (2, 4))
        self.assertEqual(self.get("X01", "FINAL", "pilot", endpoint="Q06", variant="static_feedback")["excluded"], 1)
        self.assertEqual(self.get("X01", "FINAL", "full_ext", endpoint="Q06", variant="static_feedback")["excluded"], 2)
        for pair, n in (("static_feedback-test_feedback", 3), ("static_feedback-combined_feedback", 0),
                        ("test_feedback-combined_feedback", -3)):
            self.assertEqual(self.nd("X01", "FINAL", c, endpoint="Q06", comparison=pair), (n, 9))
        for v, n in (("static_feedback", 3), ("test_feedback", 0), ("combined_feedback", 0)):
            self.assertEqual(self.nd("X01", "FINAL", c, endpoint="E02", variant=v), (n, 9))
        # the frozen R04 keeps every cell
        self.assertEqual(self.nd("R04", "FINAL", c, endpoint="Q06", variant="static_feedback"), (4, 12))
        note = self.get("X01", "FINAL", c, endpoint="Q06", variant="static_feedback")["note"]
        self.assertTrue(note.startswith(POST_FREEZE))
        self.assertIn("excluded: 3 base cell(s) = 3 with an auto-closed artifact + 0 outside", note)

    def test_x02(self):
        c = "composite"
        self.assertEqual(self.nd("X02", "BASE", c, state="DIRTY"), (8, 12))
        self.assertEqual(self.nd("X02", "BASE", c, state="NO_FINDING_INCOMPLETE"), (4, 12))
        self.assertEqual(self.nd("X02", "BASE", c, state="CLEAN_COMPLETE"), (0, 12))
        self.assertEqual(self.get("X02", "BASE", c, state="DIRTY")["dirty_only_under_frozen_rule"], 4)
        self.assertEqual(self.nd("F01", "BASE", c, state="DIRTY"), (12, 12))           # the frozen rule
        omp = self.get("X02", "BASE", c, execution_model="omp", state="DIRTY")
        self.assertEqual((omp["numerator"], omp["denominator"], omp["dirty_only_under_frozen_rule"]), (0, 4, 4))
        serial = self.get("X02", "BASE", "pilot", execution_model="serial", state="DIRTY")
        self.assertEqual((serial["numerator"], serial["denominator"], serial["dirty_only_under_frozen_rule"]),
                         (2, 2, 0))
        for v, (dirty, clean, nfi, only) in (("static_feedback", (0, 8, 4, 0)), ("test_feedback", (8, 0, 4, 4)),
                                             ("combined_feedback", (0, 8, 4, 0))):
            self.assertEqual(self.nd("X02", "FINAL", c, variant=v, state="DIRTY"), (dirty, 12))
            self.assertEqual(self.nd("X02", "FINAL", c, variant=v, state="CLEAN_COMPLETE"), (clean, 12))
            self.assertEqual(self.nd("X02", "FINAL", c, variant=v, state="NO_FINDING_INCOMPLETE"), (nfi, 12))
            self.assertEqual(self.get("X02", "FINAL", c, variant=v, state="DIRTY")["dirty_only_under_frozen_rule"],
                             only)
        # every benchmark shows 2/3 DIRTY: an interior zero-width interval, flagged
        dirty = self.get("X02", "BASE", c, state="DIRTY")
        self.assertEqual((dirty["ci_low"], dirty["ci_high"], dirty["ci_degenerate"]), (2 / 3.0, 2 / 3.0, True))
        self.assertNotIn("dirty_only_under_frozen_rule", self.get("X02", "BASE", c, state="CLEAN_COMPLETE"))

    def test_x03(self):
        c = "composite"
        expected = OrderedDict([("gcc_analyzer", 0), ("clang_tidy", 8), ("cppcheck", 0), ("infer", 0),
                                ("parcoach", 0), ("llov", 0)])
        for tool, n in expected.items():
            self.assertEqual(self.nd("X03", "BASE", c, tool=tool, quantity="dirty_only_via_tool"), (n, 12))
        self.assertEqual(self.nd("X03", "BASE", "pilot", tool="clang_tidy", quantity="dirty_only_via_tool"), (4, 6))
        checks = OrderedDict([
            (("clang_tidy", "bugprone-narrowing-conversions"), ((8, None), (8, 12), (4, 4))),
            (("clang_tidy", "bugprone-easily-swappable-parameters"), ((4, None), (4, 12), (2, 2))),
            (("infer", "INTEGER_OVERFLOW_L2"), ((8, None), (4, 8), (4, 2))),
            (("gcc_analyzer", "-Wanalyzer-a"), ((4, None), (4, 12), (2, 2))),
            (("gcc_analyzer", "-Wanalyzer-b"), ((4, None), (4, 12), (2, 2))),
        ])
        for (tool, check), (count, share, pilot) in checks.items():
            self.assertEqual(self.nd("X03", "BASE", c, tool=tool, check_id=check, quantity="blocking_findings"), count)
            self.assertEqual(self.nd("X03", "BASE", c, tool=tool, check_id=check, quantity="artifacts_with_check"),
                             share)
            self.assertEqual((self.nd("X03", "BASE", "pilot", tool=tool, check_id=check,
                                      quantity="blocking_findings")[0],
                              self.nd("X03", "BASE", "pilot", tool=tool, check_id=check,
                                      quantity="artifacts_with_check")[0]), pilot)
        rows = [e for e in self.estimates if e["metric_id"] == "X03" and e["block"] == c]
        self.assertEqual(len(rows), 6 + 2 * len(checks))
        self.assertTrue(all(e["post_freeze"] and e["ci_method"] is None for e in rows))

    def test_x03_top_n_comes_from_the_addendum(self):
        """With the X03 text saying 'the 1 check ids', each tool keeps its top
        check id; the gcc_analyzer tie (4 / 4) goes to the smaller check id."""
        addendum = copy.deepcopy(self.addendum)
        x03 = [m for m in addendum["metrics"] if m["id"] == "X03"][0]
        self.assertIn("the 10 check ids", x03["meaning"])
        x03["meaning"] = x03["meaning"].replace("the 10 check ids", "the 1 check ids")
        estimates = metrics.compute(core.Dataset(copy.deepcopy(self.tables)), self.methodology, 50, 20,
                                    exploratory=True, addendum=addendum)
        kept = sorted((e["strata"]["tool"], e["strata"]["check_id"]) for e in estimates
                      if e["metric_id"] == "X03" and e["block"] == "composite"
                      and e["strata"]["quantity"] == "blocking_findings")
        self.assertEqual(kept, [("clang_tidy", "bugprone-narrowing-conversions"), ("gcc_analyzer", "-Wanalyzer-a"),
                                ("infer", "INTEGER_OVERFLOW_L2")])

    def test_x04(self):
        c = "composite"
        self.assertEqual(self.nd("X04", "BASE", c, state="CLEAN_COMPLETE"), (0, 8))
        self.assertEqual(self.nd("X04", "BASE", c, state="NO_FINDING_INCOMPLETE"), (0, 8))
        static = self.get("X04", "FINAL", c, variant="static_feedback", state="CLEAN_COMPLETE")
        self.assertEqual((static["numerator"], static["denominator"]), (4, 4))
        # every supporting cluster at 100%: [1, 1] kept, flagged degenerate with the note sentence
        self.assertEqual((static["ci_low"], static["ci_high"], static["ci_degenerate"]), (1.0, 1.0, True))
        self.assertTrue(static["note"].startswith(POST_FREEZE))
        self.assertIn(DEGENERATE, static["note"])
        self.assertEqual(self.nd("X04", "FINAL", c, variant="combined_feedback", state="NO_FINDING_INCOMPLETE"),
                         (4, 4))
        self.assertEqual(self.nd("X04", "FINAL", c, variant="combined_feedback", state="CLEAN_COMPLETE"), (0, 4))
        self.assertEqual(self.nd("X04", "FINAL", c, variant="test_feedback", state="CLEAN_COMPLETE"), (0, 8))
        self.assertEqual(self.nd("X04", "FINAL", "pilot", variant="static_feedback", state="CLEAN_COMPLETE"), (2, 2))

    def test_x04_note_depends_on_the_state(self):
        """Regression: the NO_FINDING_INCOMPLETE share (here 4/4 for
        combined_feedback: the iteration-2 serial gcc_analyzer TIMEOUT) is
        no blocking finding plus an analysis gap - the frozen F01 rule never
        calls that clean, so its note must not label it 'statically clean'
        (the G4 quantity); the CLEAN_COMPLETE note does."""
        c = "composite"
        gap = self.get("X04", "FINAL", c, variant="combined_feedback", state="NO_FINDING_INCOMPLETE")
        self.assertEqual((gap["numerator"], gap["denominator"]), (4, 4))
        clean = self.get("X04", "FINAL", c, variant="static_feedback", state="CLEAN_COMPLETE")
        for e in (gap, clean):
            self.assertTrue(e["note"].startswith(POST_FREEZE))
        self.assertNotIn("statically clean", gap["note"])
        self.assertNotIn("(goal G4)", gap["note"])
        self.assertIn("analysis-gap state", gap["note"])
        self.assertIn("NOT clean", gap["note"])
        self.assertIn("contrast to the G4 quantity", gap["note"])
        self.assertIn("statically clean (every applicable static analysis tool COMPLETED, no reported blocking "
                      "finding) but incorrect", clean["note"])
        self.assertIn("goal G4", clean["note"])
        x04 = [e for e in self.estimates if e["metric_id"] == "X04"]
        self.assertEqual(len(x04), 3 * 4 * 2)
        for e in x04:
            self.assertEqual("statically clean" in e["note"], e["strata"]["state"] == "CLEAN_COMPLETE",
                             metrics.sort_key(e))

    def test_x05(self):
        c = "composite"
        static = self.get("X05", "TRAJECTORIES", c, variant="static_feedback")
        self.assertEqual((static["numerator"], static["denominator"], static["value"]), (12, 12, 1.0))
        self.assertEqual([self.nd("X05", "TRAJECTORIES", c, variant="static_feedback", iteration=k) for k in range(3)],
                         [(0, 12), (12, 12), (0, 12)])
        test = self.get("X05", "TRAJECTORIES", c, variant="test_feedback")
        self.assertEqual((test["numerator"], test["denominator"], test["value"]), (0, 12, 0.0))
        self.assertEqual(self.nd("X05", "TRAJECTORIES", c, variant="test_feedback", iteration=0), (12, 12))
        combined = self.get("X05", "TRAJECTORIES", c, variant="combined_feedback")        # stopped_budget only
        self.assertEqual((combined["numerator"], combined["denominator"], combined["value"]), (0, 0, None))
        self.assertIsNone(self.get("X05", "TRAJECTORIES", c, variant="combined_feedback", iteration=2)["value"])

    def test_x06(self):
        c = "composite"
        expected = {
            "static_feedback": {("pass->pass", "all_pass->all_pass"): 4,
                                ("not_pass->pass", "not_all_pass->all_pass"): 4,
                                ("not_pass->not_pass", "not_all_pass->not_all_pass"): 4},
            "test_feedback": {("pass->pass", "all_pass->all_pass"): 4,
                              ("not_pass->not_pass", "not_all_pass->not_all_pass"): 8},
            "combined_feedback": {("pass->not_pass", "all_pass->not_all_pass"): 4,
                                  ("not_pass->pass", "not_all_pass->all_pass"): 4,
                                  ("not_pass->pass", "not_all_pass->not_all_pass"): 4},
        }
        labels = lambda states: ["%s->%s" % (x, y) for x in states for y in states]  # noqa: E731
        for v, cells in expected.items():
            seen = 0
            for q in labels(("pass", "not_pass")):
                for h in labels(("all_pass", "not_all_pass")):
                    e = self.get("X06", "FINAL", c, variant=v, transition=q, heldout_transition=h)
                    self.assertEqual((e["numerator"], e["denominator"]), (cells.get((q, h), 0), 12))
                    self.assertEqual(list(e["strata"]), ["variant", "transition", "heldout_transition"])
                    seen += 1
            self.assertEqual(seen, 16)
        self.assertEqual(self.nd("X06", "FINAL", "pilot", variant="combined_feedback", transition="not_pass->pass",
                                 heldout_transition="not_all_pass->not_all_pass"), (2, 6))


class RefusalTest(unittest.TestCase):
    """Injected contradictions fail closed (core.AnalysisRefused)."""

    @classmethod
    def setUpClass(cls):
        cls.methodology = core.load_methodology()
        cls.tables = synthetic_tables(full_ext=FULL_BENCHMARKS[:2], models=("model_a",), seed=21)

    def refuses(self, mutate, recompute=False, cause=None):
        """The mutated tables refuse (with a message matching `cause` when given)."""
        tables = copy.deepcopy(self.tables)
        mutate(tables)
        if recompute:
            refresh(tables)
        with self.assertRaisesRegex(core.AnalysisRefused, cause or ""):
            metrics.compute(core.Dataset(tables), self.methodology, 5, 5, exploratory=True)

    def test_clean_fixture_computes(self):
        metrics.compute(core.Dataset(copy.deepcopy(self.tables)), self.methodology, 5, 5, exploratory=True)

    def test_duplicate_artifact(self):
        self.refuses(lambda t: t["artifacts"].append(copy.deepcopy(t["artifacts"][0])))

    def test_missing_trajectory(self):
        self.refuses(lambda t: t["trajectories"].pop(0))

    def test_unreferenced_candidate(self):
        def mutate(t):
            row = [r for r in t["trajectories"] if r["final_iteration"] >= 1][0]
            last = row["final_iteration"]
            row["final_iteration"] = last - 1
            row["artifact_iter%d" % last] = ""
            row["status_iter%d" % last] = ""
            row["status_iter%d" % (last - 1)] = row["terminal_status"]
            row["final_artifact"] = row["artifact_iter%d" % (last - 1)]
        self.refuses(mutate)

    def test_trajectory_artifact_missing(self):
        def mutate(t):
            row = [r for r in t["trajectories"] if r["final_iteration"] >= 1][0]
            gone = row["artifact_iter1"]
            t["artifacts"] = [a for a in t["artifacts"] if a["artifact_id"] != gone]
        self.refuses(mutate)

    def test_mixed_gate(self):
        def mutate(t):
            candidates = set(a["artifact_id"] for a in t["artifacts"] if a["iteration"] >= 1)
            pair = [p for p in t["enhanced_pairs"] if p["gated"] and p["artifact_id"] in candidates][0]
            pair["status"] = "pass"                  # its base artifact keeps the gate of the same group
            pair["gated"] = False
        self.refuses(mutate, recompute=True)

    def test_enhanced_column_mismatch(self):
        def mutate(t):
            t["artifacts"][0]["enh_pass"] += 1
        self.refuses(mutate)

    def test_duplicate_pair(self):
        self.refuses(lambda t: t["enhanced_pairs"].append(copy.deepcopy(t["enhanced_pairs"][0])), recompute=True)

    def test_applicable_with_inapplicable_state(self):
        def mutate(t):
            e = [e for e in t["tool_entries"] if e["applicable"] and e["tool"] == "cppcheck"][0]
            e["state"] = "NOT_APPLICABLE"
        self.refuses(mutate, recompute=True)

    def test_absent_entry_for_tool(self):
        def mutate(t):
            t["tool_entries"].pop(0)
        self.refuses(mutate)

    def test_finding_count_mismatch(self):
        def mutate(t):
            e = [e for e in t["tool_entries"] if e["applicable"] and e["tool"] == "clang_tidy"][0]
            e["num_non_blocking"] += 1
            e["num_findings"] += 1
        self.refuses(mutate)

    def test_missing_generation(self):
        self.refuses(lambda t: t["generations"].pop())

    def test_excluded_run(self):
        def mutate(t):
            t["artifacts"][0]["source_run"] = sorted(core.EXCLUDED_RUNS)[0]
        self.refuses(mutate)

    def test_benchmark_in_two_blocks(self):
        def mutate(t):
            cell = [c for c in t["base_cells"] if c["block"] == "pilot"][0]
            cell["benchmark"] = FULL_BENCHMARKS[0]
            cell["family"] = core.family_of(FULL_BENCHMARKS[0])
            cell["bl01"] = False
        self.refuses(mutate)

    def test_contradictory_compile_error(self):
        def mutate(t):
            t["artifacts"][0]["compile_error"] = not t["artifacts"][0]["compile_error"]
        self.refuses(mutate)

    def test_unequal_valid_pairs_within_cell(self):
        def mutate(t):
            row = [r for r in t["trajectories"] if r["final_iteration"] >= 1][0]
            victim = row["artifact_iter1"]
            pair = [p for p in t["enhanced_pairs"] if p["artifact_id"] == victim and not p["gated"]][0]
            t["enhanced_pairs"].remove(pair)
        self.refuses(mutate, recompute=True)

    def test_whole_tool_missing(self):
        """Regression: the tool universe is the frozen tool list - a tool
        without any entry (even where it applies) refuses."""
        for tool in ("infer", "clang_tidy", "tsan", "must"):
            def mutate(t, tool=tool):
                t["tool_entries"] = [e for e in t["tool_entries"] if e["tool"] != tool]
                t["findings"] = [f for f in t["findings"] if f["tool"] != tool]
            self.refuses(mutate, recompute=True, cause="no tool entry of the frozen tool")

    def test_tool_scope_cross_check(self):
        scope = OrderedDict((stage, OrderedDict((t, list(APPLIES[t])) for t in APPLIES if STAGE[t] == stage))
                            for stage in ("static", "dynamic"))
        metrics.compute(core.Dataset(copy.deepcopy(self.tables), OrderedDict([("tool_scope", scope)])),
                        self.methodology, 5, 5, exploratory=True)
        for stage, tool, models in (("static", "infer", ["serial"]), ("dynamic", "tsan", ["omp", "mpi"])):
            wrong = copy.deepcopy(scope)
            wrong[stage][tool] = models
            with self.assertRaises(core.AnalysisRefused):
                metrics.compute(core.Dataset(copy.deepcopy(self.tables), OrderedDict([("tool_scope", wrong)])),
                                self.methodology, 5, 5, exploratory=True)
        fewer = copy.deepcopy(scope)
        del fewer["static"]["llov"]
        with self.assertRaises(core.AnalysisRefused):
            metrics.compute(core.Dataset(copy.deepcopy(self.tables), OrderedDict([("tool_scope", fewer)])),
                            self.methodology, 5, 5, exploratory=True)

    def test_unknown_finding_family(self):
        self.assertEqual(metrics.finding_families(self.methodology),
                         ("memory", "uninitialized", "null_deref", "arithmetic", "race", "deadlock", "mpi_usage",
                          "api_misuse", "build", "other"))

        def mutate(t):
            t["findings"][0]["family"] = "data_race"          # a renamed class would silently zero F06 race
        self.refuses(mutate, cause="outside the frozen class vocabulary")

    def test_null_input_or_output_tokens(self):
        for field in ("input_tokens", "output_tokens"):
            def mutate(t, field=field):
                t["generations"][-1][field] = None
            self.refuses(mutate, cause="only reasoning_tokens may be null")
        tables = copy.deepcopy(self.tables)
        tables["generations"][-1]["reasoning_tokens"] = None   # the provider reports no field: allowed
        metrics.compute(core.Dataset(tables), self.methodology, 5, 5, exploratory=True)

    def test_replicates_must_follow_methodology(self):
        """Regression: confirmatory p-values / Holm decisions (and the published
        intervals) rest on the frozen replicate counts only."""
        dataset = lambda: core.Dataset(copy.deepcopy(self.tables))  # noqa: E731
        for primary, descriptive in ((3, 3), (3, None), (None, 3)):
            with self.assertRaises(core.AnalysisRefused):
                metrics.compute(dataset(), self.methodology, primary, descriptive)
        clusters = metrics.cohorts(dataset())["clusters"]
        small = stats.ClusterBootstrap(clusters, 5, 20261017, 0.95)
        with self.assertRaises(core.AnalysisRefused):
            metrics.compute(dataset(), self.methodology, small, None)
        with self.assertRaises(core.AnalysisRefused):
            metrics.compute_primary(dataset(), self.methodology, 200)
        frozen = metrics.compute_primary(dataset(), self.methodology)              # 10,000 replicates
        self.assertEqual(len(frozen), 12)
        self.assertTrue(all(0 < e["replicates"] <= 10000 and e["reject_holm"] is not None for e in frozen))
        self.assertTrue(all("EXPLORATORY" not in e["note"] for e in frozen))
        trial = metrics.compute_primary(dataset(), self.methodology, 3, exploratory=True)
        self.assertTrue(all("EXPLORATORY: 3 bootstrap replicates (methodology 10000), not confirmatory"
                            in e["note"] for e in trial))

    def test_given_bootstrap_must_match(self):
        dataset = core.Dataset(copy.deepcopy(self.tables))
        clusters = metrics.cohorts(dataset)["clusters"]
        good = stats.ClusterBootstrap(clusters, 5, 20261017, 0.95)
        metrics.compute(dataset, self.methodology, good, 5, exploratory=True)
        wrong_seed = stats.ClusterBootstrap(clusters, 5, 1, 0.95)
        with self.assertRaises(core.AnalysisRefused):
            metrics.compute(core.Dataset(copy.deepcopy(self.tables)), self.methodology, wrong_seed, 5,
                            exploratory=True)
        other = OrderedDict(list(clusters.items())[:-1])
        with self.assertRaises(core.AnalysisRefused):
            metrics.compute(core.Dataset(copy.deepcopy(self.tables)), self.methodology,
                            stats.ClusterBootstrap(other, 5, 20261017, 0.95), 5, exploratory=True)

    def test_addendum_binding_and_wording(self):
        """The X metrics implement exactly the declared addendum: another
        methodology binding, renamed / extra metrics, a missing top-N, a
        reworded vocabulary or other estimate fields refuse."""
        addendum = core.load_addendum(methodology=self.methodology)

        def run(doc):
            return metrics.compute(core.Dataset(copy.deepcopy(self.tables)), self.methodology, 5, 5,
                                   exploratory=True, addendum=doc)
        produced = set(e["metric_id"] for e in run(copy.deepcopy(addendum)))
        self.assertEqual(produced, set(core.all_metric_ids(self.methodology, addendum)))

        def meaning(metric, old, new):
            def edit(doc):
                m = [x for x in doc["metrics"] if x["id"] == metric][0]
                self.assertIn(old, m["meaning"])
                m["meaning"] = m["meaning"].replace(old, new)
            return edit
        cases = [
            (lambda d: d["amends"].update(methodology_canonical_sha256="0" * 64), "another methodology"),
            (lambda d: d.update(status="DRAFT"), "addendum with status"),
            (lambda d: d.update(addendum_id=core.ANALYSIS_ID + ".addendum_2"), "is not"),
            (lambda d: d["metrics"][1].update(name="three_state_literal_reading"), "addendum metrics are not"),
            (lambda d: d["metrics"].append(OrderedDict([("id", "X07"), ("name", "extra")])),
             "addendum metrics are not"),
            (lambda d: d["metrics"].pop(), "addendum metrics are not"),
            (lambda d: d["estimate_fields"].pop(), "estimate fields"),
            (meaning("X03", "the 10 check ids", "the top check ids"), "check-id count"),
            (meaning("X02", "COMPLETED or PARTIAL", "COMPLETED"), "X02 meaning"),
            (meaning("X05", "stopped_clean or stopped_tests_pass", "stopped_clean"), "X05 meaning"),
            (meaning("X01", "clean_auto_closed", "auto-closed"), "X01 meaning"),
        ]
        for mutate, cause in cases:
            doc = copy.deepcopy(addendum)
            mutate(doc)
            with self.assertRaisesRegex(core.AnalysisRefused, cause):
                run(doc)
        with self.assertRaises(core.AnalysisRefused):
            run([])

    def test_post_freeze_guard(self):
        """Every stored estimate: post_freeze exactly for X01-X06, and an
        addendum estimate's note starts with the post-freeze label."""
        builder = metrics._Builder(core.Dataset(copy.deepcopy(self.tables)), self.methodology, 5, 5,
                                   exploratory=True, addendum=core.load_addendum(methodology=self.methodology))
        strata = (("endpoint", "Q06"), ("variant", "static_feedback"))
        for est in (metrics.estimate("X01", "FINAL", "composite", strata, note=POST_FREEZE + "x"),
                    metrics.estimate("X01", "FINAL", "composite", strata, note="no label", post_freeze=True),
                    metrics.estimate("R04", "FINAL", "composite", strata, note=POST_FREEZE + "x", post_freeze=True)):
            with self.assertRaises(core.AnalysisRefused):
                builder._put(est)
        builder._put(metrics.estimate("X01", "FINAL", "composite", strata, note=POST_FREEZE + "x", post_freeze=True))

    def test_reported_blocking_without_check_id(self):
        def mutate(t):
            f = [f for f in t["findings"] if f["kind"] == "reported_blocking" and f["tool"] == "clang_tidy"][0]
            f["check_id"] = ""
        self.refuses(mutate, cause="without a check id")

    def test_check_id_gates_only_the_addendum(self):
        """Regression: the check id is an X03 strata value only. A missing one
        refuses compute() (X03) but not the frozen primary family: the
        reproducibility rerun compute_primary reads no check id and gives the
        same 12 hypotheses as on the intact fixture."""
        for missing in ("", None):
            tables = copy.deepcopy(self.tables)
            base = set(a["artifact_id"] for a in tables["artifacts"] if a["iteration"] == 0)
            f = [f for f in tables["findings"] if f["kind"] == "reported_blocking" and f["tool"] == "clang_tidy"
                 and f["artifact_id"] in base][0]
            f["check_id"] = missing
            with self.assertRaisesRegex(core.AnalysisRefused, "without a check id"):
                metrics.compute(core.Dataset(copy.deepcopy(tables)), self.methodology, 5, 5, exploratory=True)
            primary = metrics.compute_primary(core.Dataset(tables), self.methodology, 5, exploratory=True)
            intact = metrics.compute_primary(core.Dataset(copy.deepcopy(self.tables)), self.methodology, 5,
                                             exploratory=True)
            self.assertEqual(len(primary), 12)
            self.assertEqual(json.dumps(primary), json.dumps(intact))

    def test_p_resolution_uses_the_drawn_replicates(self):
        """Regression: p_resolution = 2 / replicates_primary (the DRAWN count,
        DESIGN2 section 1 and the tables / validate checks), also for a
        hypothesis whose p-value rests on fewer usable replicates (resamples
        with a zero denominator skipped) - its note states the usable count."""
        drawn = 200
        tables = synthetic_tables(seed=4, gate_share=0.9, pairs=1)       # mostly gated: E02 cohort is small
        family = metrics.compute_primary(core.Dataset(tables), self.methodology, drawn, exploratory=True)
        skipped = [e for e in family if e["replicates"] < drawn]
        self.assertGreater(len(skipped), 0)                              # precondition: some replicates skipped
        self.assertLess(len(skipped), 12)
        for e in family:
            self.assertEqual(e["p_resolution"], 2.0 / drawn, metrics.sort_key(e))
            self.assertEqual(e["p_holm_resolution"], 12 * 2.0 / drawn)     # one resolution: m * 2 / B throughout
            usable = "the p-value rests on %d usable replicates, its smallest positive value is 2 / %d" % (
                e["replicates"], e["replicates"])
            self.assertEqual(usable in e["note"], e["replicates"] < drawn, metrics.sort_key(e))
            if e["replicates"] < drawn:
                self.assertIn("%d of %d bootstrap replicates skipped" % (drawn - e["replicates"], drawn), e["note"])


if __name__ == "__main__":
    unittest.main()
