"""Tests of the study tables (tables.py) and their LaTeX / CSV / JSON
renderings (latex.py) on SYNTHETIC estimates that follow the conventions of
spec section 3.2 (documented in tables.py). The fixture is shared with
test_figures.py.

    python3 -B -m unittest -v thesis.study_analysis.test_tables
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import re
import unittest
from collections import OrderedDict

from thesis.study_analysis import core, latex, tables

METHODOLOGY = core.load_methodology()
ADDENDUM = core.load_addendum(methodology=METHODOLOGY)
ADDENDUM_IDS = tuple(core.addendum_metric_ids(ADDENDUM))
NOTES = OrderedDict((n["id"], n["text"]) for n in ADDENDUM["table_notes"])
CAVEATS = OrderedDict((c["id"], c["text"]) for c in ADDENDUM["interpretive_caveats"])
MODELS = ("model_a", "model_b")
EXEC = tuple(METHODOLOGY["strata"]["execution_model"])
VARIANTS = tuple(METHODOLOGY["strata"]["variant"])
BLOCKS = tuple(METHODOLOGY["strata"]["block"])
STEPS = tuple(METHODOLOGY["strata"]["iteration"])
BENCHMARKS = OrderedDict([("pilot", 4), ("full_ext", 12)])
CELLS = OrderedDict([("pilot", 4), ("full_ext", 12), ("composite", 16)])   # per (model, execution model)
DESCRIPTIVE = int(METHODOLOGY["statistics"]["bootstrap"]["replicates_descriptive"])
PRIMARY = int(METHODOLOGY["statistics"]["bootstrap"]["replicates_primary"])


def pseudo(key, upper):
    """Deterministic pseudo count in [0, upper]."""
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % (upper + 1)


# -- synthetic dataset --------------------------------------------------------------------------------

def synthetic_dataset():
    rows = OrderedDict((name, []) for name in core.SCHEMAS)
    for block, n_bench in BENCHMARKS.items():
        base_run = core.BLOCK_BASE_RUN[block]
        for b in range(n_bench):
            family = "fam%d" % (b % 2)
            benchmark = "%s/%02d_%s" % (family, b, block)
            for model in MODELS:
                for em in EXEC:
                    sample = "%s__%s__%s__sample_0" % (model, benchmark.replace("/", "__"), em)
                    cell = core.cell_id(block, model, sample)
                    rows["base_cells"].append(OrderedDict([
                        ("cell_id", cell), ("block", block), ("model_id", model), ("benchmark", benchmark),
                        ("family", family), ("execution_model", em), ("sample_id", sample), ("base_run", base_run),
                        ("source_sha256", "0" * 64), ("bl01", block == "pilot" and b == 3)]))
                    facts = (block, model, benchmark, family, em, sample, cell, b)
                    base_art = _artifact(rows, facts, base_run, "", 0, "")
                    for v in VARIANTS:
                        final = pseudo(cell + v, 2)
                        status = ("stopped_budget" if final == 2 else
                                  ("stopped_analysis_incomplete" if final == 1 else
                                   ("stopped_clean" if pseudo(cell + v + "s", 1) else "stopped_tests_pass")))
                        arts = [base_art]
                        for k in range(1, final + 1):
                            run = "%s__%s__iter%d" % (base_run, v, k)
                            arts.append(_artifact(rows, facts, run, v, k, base_run))
                        arts += [""] * (3 - len(arts))
                        rows["trajectories"].append(OrderedDict([
                            ("trajectory_id", core.trajectory_id(cell, v)), ("cell_id", cell), ("block", block),
                            ("model_id", model), ("variant", v), ("loop_owner", base_run), ("loop_kind", "native"),
                            ("final_iteration", final), ("terminal_status", status), ("stop_reason", "x"),
                            ("status_iter0", "active" if final else status), ("status_iter1", ""), ("status_iter2", ""),
                            ("test_verdict_final", ""), ("artifact_iter0", arts[0]), ("artifact_iter1", arts[1]),
                            ("artifact_iter2", arts[2]), ("final_artifact", arts[final]), ("request_rounds", final)]))
    return core.Dataset(rows, OrderedDict([("targets_sha256", "t" * 8), ("census_digest", "c" * 8)]))


def _artifact(rows, facts, run, variant, iteration, loop_owner):
    block, model, benchmark, family, em, sample, cell, b_index = facts
    art = core.artifact_id(block, model, run, sample)
    gated = 1 if b_index == 0 else 0
    supplemented = OrderedDict([("parcoach", "full_ext_recovery_002")]) if (block == "full_ext" and b_index == 1) \
        else OrderedDict()
    rows["artifacts"].append(OrderedDict([
        ("artifact_id", art), ("cell_id", cell), ("block", block), ("model_id", model), ("benchmark", benchmark),
        ("family", family), ("execution_model", em), ("sample_id", sample), ("variant", variant),
        ("iteration", iteration), ("source_run", run), ("loop_owner", loop_owner),
        ("correctness_owner", run), ("static_owner", run), ("static_supplemented_by", supplemented),
        ("dynamic_owner", run), ("enhanced_owner", "pilot_002" if block == "pilot" else "full_ext_phase2_001"),
        ("enh_pairs", 2), ("enh_valid", 2 - gated), ("enh_gated", gated)]))
    rows["generations"].append(OrderedDict([("artifact_id", art), ("kind", "repair" if iteration else "base")]))
    for stage, tools_ in (("static", core.STATIC_TOOLS), ("dynamic", core.DYNAMIC_TOOLS)):
        for tool in tools_:                    # every tool ran on every artifact of the fixture
            rows["tool_entries"].append(OrderedDict([("artifact_id", art), ("stage", stage), ("tool", tool),
                                                     ("ran", True)]))
    for spec in ("spec0", "spec1"):
        rows["enhanced_pairs"].append(OrderedDict([
            ("artifact_id", art), ("spec_key", spec), ("status", "baseline_incompatible" if (gated and spec == "spec0")
                                                       else "pass"),
            ("gated", bool(gated and spec == "spec0"))]))
    return art


# -- synthetic estimates -----------------------------------------------------------------------------------

class Synth:
    def __init__(self):
        self.out = []

    def est(self, metric, population, block, strata, num, den, ci=False, primary=False, value=None, **extra):
        if value is None and num is not None:
            value = (float(num) / den) if den else None
        e = OrderedDict([
            ("metric_id", metric), ("population", population), ("block", block), ("strata", OrderedDict(strata)),
            ("numerator", num), ("denominator", den), ("value", value),
            ("ci_low", None if (value is None or not ci) else value - 0.05),
            ("ci_high", None if (value is None or not ci) else value + 0.04),
            ("ci_method", tables.CI_METHOD if ci else None),
            ("replicates", (PRIMARY if primary else DESCRIPTIVE) if ci else None),
            ("p_value", None), ("p_holm", None), ("reject_holm", None), ("note", None)])
        # the DESIGN2 section-1 contract keys
        e["post_freeze"] = metric in ADDENDUM_IDS
        e["ci_degenerate"] = None if e["ci_low"] is None else e["ci_low"] == e["ci_high"]
        e["p_resolution"] = e["p_holm_resolution"] = None
        if metric in tables.EXCLUSION_REASONS and not (metric == "G01" and "comparison" in e["strata"]):
            e["excluded"] = 0                  # metrics.py: the count of the methodology's exclusion rule
        e.update(extra)
        self.out.append(e)
        return e

    def find(self, metric, population, block, strata):
        key = tables.strata_key(strata)
        hits = [e for e in self.out if e["metric_id"] == metric and e["population"] == population
                and e["block"] == block and tables.strata_key(e["strata"]) == key]
        assert len(hits) == 1, (metric, population, block, strata, len(hits))
        return hits[0]


def strata_forms(with_full=True):
    forms = [OrderedDict()]
    forms += [OrderedDict([("execution_model", em)]) for em in EXEC]
    forms += [OrderedDict([("model_id", m)]) for m in MODELS]
    if with_full:
        forms += [OrderedDict([("model_id", m), ("execution_model", em)]) for m in MODELS for em in EXEC]
    return forms


def cells_of(block, strata):
    n = CELLS[block]
    if "model_id" not in strata:
        n *= len(MODELS)
    if "execution_model" not in strata:
        n *= len(EXEC)
    return n


def synthetic_estimates(dataset=None):
    dataset = dataset or synthetic_dataset()
    s = Synth()
    for block in BLOCKS:
        for strata in strata_forms():
            den = cells_of(block, strata)
            tag = "%s|%s" % (block, json.dumps(strata))
            for metric in ("Q01", "Q02", "Q03", "Q05", "Q07", "Q09", "F03", "F04", "S03", "D03", "E05"):
                s.est(metric, "BASE", block, strata, pseudo(metric + tag, den), den, ci=metric == "Q05")
            for flag in core.CLEANING_FLAGS + ("any", "any_including_fence"):
                s.est("Q04", "BASE", block, dict(strata, flag=flag), pseudo("Q04" + flag + tag, den // 3), den)
            verdicts = list(core.CORRECTNESS_VERDICTS)
            remaining = den
            for verdict in verdicts[:-2]:
                n = pseudo("Q08" + verdict + tag, remaining // 2)
                s.est("Q08", "BASE", block, dict(strata, verdict=verdict), n, den)
                remaining -= n
            s.est("Q08", "BASE", block, dict(strata, verdict=verdicts[-2]), remaining, den)
            for metric, unit in (("Q06", 1), ("E01", 20), ("E02", 1), ("Q10", 1)):
                d = den * unit
                pop = (lambda p: "ENH_PAIRS(%s)" % p) if metric == "E01" else (lambda p: p)
                base = s.est(metric, pop("BASE"), block, strata, pseudo(metric + tag, d), d, ci=metric != "Q10")
                for v in VARIANTS:
                    vs = dict(strata, variant=v)
                    final = s.est(metric, pop("FINAL"), block, vs, pseudo(metric + v + tag, d), d,
                                  ci=metric != "Q10")
                    if metric == "Q10":
                        continue
                    for k in STEPS:
                        num = base["numerator"] if k == STEPS[0] else (
                            final["numerator"] if k == STEPS[-1] else pseudo(metric + v + str(k) + tag, d))
                        s.est(metric, pop("STEP"), block, dict(vs, step=k), num, d, ci=True)
                        if not strata:                   # G02 = the same rates per step (goal G3)
                            s.est("G02", "STEP", block, {"endpoint": metric, "variant": v, "step": k}, num, d,
                                  ci=True)
            for metric in ("Q06", "E02"):
                for v in VARIANTS:
                    es = dict(strata, endpoint=metric, variant=v)
                    if block == "composite" and not strata:      # ratio of sums: the blocks add up
                        parts = [(s.find("R02", "FINAL", b, es), s.find("R03", "FINAL", b, es)) for b in BLOCKS[:2]]
                        fail = sum(r02["denominator"] for r02, _ in parts)
                        improved = sum(r02["numerator"] for r02, _ in parts)
                        regressed = sum(r03["numerator"] for _, r03 in parts)
                    else:
                        fail = pseudo("fail" + metric + v + tag, den)
                        improved = pseudo("imp" + metric + v + tag, fail)
                        regressed = pseudo("reg" + metric + v + tag, den - fail)
                    s.est("R02", "FINAL", block, es, improved, fail, ci=True)
                    s.est("R03", "FINAL", block, es, regressed, den - fail, ci=True)
                    primary = block == "composite" and not strata
                    r04 = s.est("R04", "FINAL", block, es, improved - regressed, den, ci=True, primary=primary)
                    if primary:
                        r04["p_value"] = 0.001 * (1 + VARIANTS.index(v)) * (1 + ("Q06", "E02").index(metric))
                    if not strata:      # SA1 covers Q06 R02 R04 R05 (no R03), both endpoints' differences
                        sa = dict(es, sensitivity="SA1")
                        s.est("R02", "FINAL", block, sa, max(improved - 1, 0), max(fail - 2, 0), ci=True)
                        s.est("R04", "FINAL", block, sa, improved - regressed - 1, den - 6, ci=True)
                        # R01: the transition labels (T7c reads them for X06)
                        labels = (("pass", "not_pass") if metric == "Q06" else ("all_pass", "not_all_pass"))
                        remaining = den
                        for i, (a, b) in enumerate((x, y) for x in labels for y in labels):
                            n = remaining if i == 3 else pseudo("r01" + metric + v + a + b + tag, remaining // 3)
                            remaining -= n
                            s.est("R01", "FINAL", block, dict(es, transition="%s->%s" % (a, b)), n, den)
            if not ("model_id" in strata and "execution_model" in strata):
                for metric in ("F01", "F02"):
                    dirty = pseudo(metric + "D" + tag, den // 2)
                    clean = pseudo(metric + "C" + tag, den - dirty)
                    for state, n in (("DIRTY", dirty), ("CLEAN_COMPLETE", clean),
                                     ("NO_FINDING_INCOMPLETE", den - dirty - clean)):
                        s.est(metric, "BASE", block, dict(strata, state=state), n, den)
                    if metric == "F01" and "model_id" not in strata:     # X02 strata: {} and execution model
                        _x02(s, "BASE", block, strata, dirty, clean, den, tag)
            if not strata:                       # F01 FINAL[v] (+ X02 FINAL) for T12
                for v in VARIANTS:
                    dirty = pseudo("F01F" + v + tag, den // 2)
                    clean = pseudo("F01FC" + v + tag, den - dirty)
                    for state, n in (("DIRTY", dirty), ("CLEAN_COMPLETE", clean),
                                     ("NO_FINDING_INCOMPLETE", den - dirty - clean)):
                        s.est("F01", "FINAL", block, {"variant": v, "state": state}, n, den)
                    _x02(s, "FINAL", block, {"variant": v}, dirty, clean, den, tag + v)
            if not strata:
                s.est("Q06", "BASE", block, {"sensitivity": "SA1"}, pseudo("sa1" + tag, den - 6), den - 6, ci=True)
                for v in VARIANTS:
                    s.est("Q06", "FINAL", block, {"sensitivity": "SA1", "variant": v}, pseudo("sa1" + v + tag, den - 6),
                          den - 6, ci=True)
            s.est("E04", "ENH_PAIRS(BASE)", block, strata, pseudo("e04" + tag, den // 4), den * 2)
    _pairs_and_trajectories(s, dataset)
    _tools(s, dataset)
    _primary(s)
    _effort(s)
    _addendum(s)
    return s.out


def _x02(s, population, block, strata, dirty, clean, den, tag):
    """X02 = F01 with the gap-state findings dropped: dirty-only artifacts move to NO_FINDING_INCOMPLETE."""
    only = pseudo("x02only" + population + tag, dirty // 3)
    for state, n in (("DIRTY", dirty - only), ("CLEAN_COMPLETE", clean),
                     ("NO_FINDING_INCOMPLETE", den - dirty - clean + only)):
        extra = {"dirty_only_under_frozen_rule": only} if state == "DIRTY" else {}
        s.est("X02", population, block, dict(strata, state=state), n, den, ci=state == "DIRTY", **extra)


X03_CHECKS = OrderedDict([("clang_tidy", ("bugprone-easily-swappable-parameters", "narrowing-conversions",
                                          "misc-unused")), ("cppcheck", ("nullPointer",))])


def _addendum(s):
    """X01-X06 in the contract shapes (DESIGN2 section 1)."""
    comparisons = [(VARIANTS[i], VARIANTS[j]) for i in range(3) for j in range(i + 1, 3)]
    findings = OrderedDict()
    for block in BLOCKS:
        den = cells_of(block, {})
        for endpoint in tables.ENDPOINTS:
            for label in [{"variant": v} for v in VARIANTS] + [{"comparison": "%s-%s" % c} for c in comparisons]:
                strata = dict(label, endpoint=endpoint)
                s.est("X01", "FINAL", block, strata, pseudo("x01" + block + json.dumps(strata), 10) - 3, den - 4,
                      ci=True, excluded=4, statistic="difference")
        dirty = s.find("F01", "BASE", block, {"state": "DIRTY"})["numerator"]
        for tool in core.STATIC_ANALYSIS_TOOLS:
            s.est("X03", "BASE", block, {"tool": tool, "quantity": tables.X03_DIRTY_ONLY},
                  pseudo("x03" + tool + block, dirty // 7), dirty)
            for check in X03_CHECKS.get(tool, ()):
                base = {"tool": tool, "check_id": check}
                if block == "composite":
                    n = findings[("pilot", tool, check)] + findings[("full_ext", tool, check)]
                else:
                    n = findings[(block, tool, check)] = pseudo("x03f" + tool + check + block, 400) + 1
                s.est("X03", "BASE", block, dict(base, quantity=tables.X03_FINDINGS), n, None, value=None)
                s.est("X03", "BASE", block, dict(base, quantity=tables.X03_ARTIFACTS),
                      pseudo("x03a" + tool + check + block, den), den)
        for population, strata in [("BASE", {})] + [("FINAL", {"variant": v}) for v in VARIANTS]:
            q06 = s.find("Q06", population, block, strata)
            fail = q06["denominator"] - q06["numerator"]          # contract: the artifacts failing Q06
            for state in tables.X04_STATES:
                s.est("X04", population, block, dict(strata, state=state),
                      pseudo("x04" + state + block + json.dumps(strata), fail // 2), fail, ci=True)
        for v in VARIANTS:
            counts = [pseudo("x05" + block + v + str(k), 30) + 1 for k in range(core.MAX_ITERATIONS + 1)]
            total = sum(counts)
            s.est("X05", "TRAJECTORIES", block, {"variant": v}, sum(k * n for k, n in enumerate(counts)), total,
                  statistic="mean")
            for k, n in enumerate(counts):
                s.est("X05", "TRAJECTORIES", block, {"variant": v, "iteration": k}, n, total, statistic="share")
            # X06: the cells in both paired cohorts (here both R04 cohorts are all base cells, so the whole
            # block) with their R01 Q06 / E02 transitions as marginals (north-west corner joint table)
            marginals = []
            for endpoint, states in (("Q06", ("pass", "not_pass")), ("E02", ("all_pass", "not_all_pass"))):
                labels = ["%s->%s" % (a, b) for a in states for b in states]
                marginals.append([(label, s.find("R01", "FINAL", block, {"endpoint": endpoint, "variant": v,
                                                                         "transition": label})["numerator"])
                                  for label in labels])
            for (q, h), n in northwest_corner(*marginals).items():
                s.est("X06", "FINAL", block, {"variant": v, "transition": q, "heldout_transition": h}, n, den)


def northwest_corner(rows, cols):
    """A joint table (row label, column label) -> count with exactly these
    marginals ([(label, count)] each, equal totals)."""
    assert sum(n for _, n in rows) == sum(n for _, n in cols)
    left_rows, left_cols = [n for _, n in rows], [n for _, n in cols]
    out = OrderedDict(((q, h), 0) for q, _ in rows for h, _ in cols)
    i = j = 0
    while i < len(rows) and j < len(cols):
        n = min(left_rows[i], left_cols[j])
        out[(rows[i][0], cols[j][0])] += n
        left_rows[i] -= n
        left_cols[j] -= n
        if left_rows[i] == 0:
            i += 1
        else:
            j += 1
    return out


def _pairs_and_trajectories(s, dataset):
    facts = tables.summarize_dataset(dataset)["blocks"]
    counts = OrderedDict()
    for row in dataset.rows("trajectories"):
        for block in (row["block"], "composite"):
            key = (block, row["variant"], row["terminal_status"])
            counts[key] = counts.get(key, 0) + 1
    for block in BLOCKS:
        f = facts[block]
        s.est("E04", "ENH_PAIRS(GENERATED)", block, {}, f["enhanced_gated"], f["enhanced_pairs"],
              gated_groups=f["gated_groups"])
        for v in VARIANTS:
            total = sum(n for (b, vv, _), n in counts.items() if b == block and vv == v)
            for (b, vv, status), n in counts.items():
                if b == block and vv == v:
                    s.est("R06", "TRAJECTORIES", block, {"variant": v, "status": status}, n, total)
            s.est("R07", "TRAJECTORIES", block, {"variant": v}, counts.get((block, v, "stopped_budget"), 0), total)
            s.est("R08", "TRAJECTORIES", block, {"variant": v},
                  counts.get((block, v, "stopped_analysis_incomplete"), 0), total)
            s.est("R09", "TRAJECTORIES", block, {"variant": v}, pseudo("r09" + block + v, total), total)
            s.est("R10", "TRAJECTORIES", block, {"variant": v}, pseudo("r10" + block + v, total), total)
            g01 = s.est("G01", "FINAL", block, {"variant": v}, pseudo("g01" + block + v, 10), 10, ci=True)
            e05 = [e for e in s.out if e["metric_id"] == "E05" and e["block"] == block and not e["strata"]][0]
            diff = s.est("G01", "FINAL", block, {"variant": v, "comparison": "G01-E05(BASE)"}, g01["numerator"],
                         g01["denominator"], ci=True, reference_numerator=e05["numerator"],
                         reference_denominator=e05["denominator"])
            diff["value"] = g01["value"] - e05["value"]
            diff["ci_low"], diff["ci_high"] = diff["value"] - 0.1, diff["value"] + 0.1


def _tools(s, dataset):
    ran = tables.summarize_dataset(dataset)["blocks"]
    for block in BLOCKS:
        den = cells_of(block, {}) * 3
        for metric, cov, tools_ in (("S01", "S02", core.STATIC_TOOLS), ("D01", "D02", core.DYNAMIC_TOOLS)):
            for tool in tools_:
                completed = pseudo(metric + tool + block, den // 2) + den // 3
                partial = pseudo(metric + tool + block + "p", den - completed)
                s.est(metric, "GENERATED", block, {"tool": tool, "state": "COMPLETED"}, completed, den)
                s.est(metric, "GENERATED", block, {"tool": tool, "state": "PARTIAL"}, partial, den)
                s.est(metric, "GENERATED", block, {"tool": tool, "state": "NOT_APPLICABLE"}, den - completed - partial,
                      den)
                for population, d in (("BASE", den // 3), ("GENERATED", den)):
                    s.est(cov, population, block, {"tool": tool}, pseudo(cov + tool + block + population, d), d)
                for em in ("all",) + EXEC:
                    for rule in (tables.C04_ALL, tables.C04_EXCL):
                        n = 20 if rule == tables.C04_ALL else 19
                        strata = {"tool": tool, "outlier_rule": rule}
                        if em != "all":
                            strata["execution_model"] = em
                        entries = ran[block]["ran_entries"][tool]
                        s.est("C04", "GENERATED", block, strata, None, n, value=1.5 + pseudo(tool + em + rule, 100)
                              / 10.0, p95=12.25, n=n, timeouts=pseudo(tool + em, 2),
                              ran_entries=sum(entries.values()) if em == "all" else entries[em])
        for tool, family in (("gcc_analyzer", "memory"), ("tsan", "race"), ("cppcheck", "null_deref")):
            for population in ("BASE", "GENERATED"):
                for kind in core.FINDING_KINDS:
                    if tool == "tsan" and kind == "low_confidence":
                        continue
                    with_finding = pseudo(tool + family + kind + population + block + "a", den)
                    n = with_finding + pseudo(tool + family + kind + population + block, 1500)
                    strata = {"tool": tool, "family": family, "kind": kind}
                    s.est("F05", population, block, dict(strata, quantity=tables.F05_FINDINGS), n, None)
                    s.est("F05", population, block, dict(strata, quantity=tables.F05_ARTIFACTS), with_finding, den)
        for pair, klass in (("tsan+llov", "race"), ("must+parcoach", "mpi_usage+deadlock"),
                            ("asan_ubsan+memcheck", "memory"), ("gcc_analyzer+cppcheck", "memory+null_deref")):
            n11, n10, n01, n00 = 3, 1, 2, 30
            s.est("F06", "GENERATED", block, {"pair": pair, "class": klass}, n11, n11 + n10 + n01 + n00,
                  n11=n11, n10=n10, n01=n01, n00=n00, positive_agreement=0.5455, kappa=0.4512)


def _primary(s):
    comparisons = [(VARIANTS[i], VARIANTS[j]) for i in range(3) for j in range(i + 1, 3)]
    for block in BLOCKS:
        den = cells_of(block, {})
        for endpoint in ("Q06", "E02"):
            for a, b in comparisons:
                strata = {"endpoint": endpoint, "comparison": "%s-%s" % (a, b)}
                num = (sum(s.find("R05", "FINAL", b, strata)["numerator"] for b in BLOCKS[:2]) if block == "composite"
                       else pseudo(endpoint + a + b + block, 20) - 10)
                e = s.est("R05", "FINAL", block, strata, num, den, ci=True, primary=block == "composite")
                s.est("R05", "FINAL", block, dict(strata, sensitivity="SA1"), e["numerator"] - 1, den - 6, ci=True)
                if block == "composite":
                    e["p_value"] = 0.02 + 0.01 * comparisons.index((a, b))
    family = [e for e in s.out if e["block"] == "composite" and e["metric_id"] in ("R04", "R05")
              and e["p_value"] is not None]
    set_holm(family)


def set_holm(family):
    """Holm step-down and the contract resolutions (p_resolution = 2/B, p_holm_resolution = running maximum
    of (m - rank + 1) * p_resolution over the Holm order)."""
    ordered_family = sorted(family, key=lambda e: e["p_value"])
    m = len(ordered_family)
    running = resolution = 0.0
    for i, e in enumerate(ordered_family):
        running = max(running, min(1.0, (m - i) * e["p_value"]))
        e["p_holm"] = running
        e["reject_holm"] = running <= 0.05
        e["p_resolution"] = 2.0 / PRIMARY
        resolution = max(resolution, (m - i) * e["p_resolution"])
        e["p_holm_resolution"] = resolution


def _effort(s):
    for block in BLOCKS:
        for v in VARIANTS:
            n = pseudo("c01" + block + v, 50) + 10
            for quantity in ("records_per_trajectory", "request_rounds_per_trajectory"):
                s.est("C01", "REPAIR_CANDIDATES", block, {"variant": v, "quantity": quantity}, n + 3, n,
                      statistic="mean")
            for strata in [{"variant": v}] + [{"variant": v, "model_id": m} for m in MODELS]:
                for kind in ("input_tokens", "output_tokens", "reasoning_tokens"):
                    tokens = 1000 * (pseudo(kind + block + v + json.dumps(strata), 900) + 100)
                    s.est("C02", "REPAIR_CANDIDATES", block, dict(strata, quantity=kind), tokens, n,
                          value=float(tokens) / n, coverage=1.0, generations=n)
            s.est("C03", "REPAIR_CANDIDATES", block, {"variant": v}, None, n, value=12.5, p95=40.25, n=n)
            for quantity, den in (("per_1M_output_tokens", 2500000), ("per_100_requests", 400)):
                improved = pseudo("c05" + block + v, 30)
                s.est("C05", "FINAL", block, {"variant": v, "quantity": quantity}, improved, den,
                      value=improved * (1e6 if quantity.startswith("per_1M") else 100.0) / den)
        s.est("C02", "BASE", block, {"quantity": "output_tokens"}, 123456, cells_of(block, {}), value=1286.0)


# -- LaTeX structure checks ----------------------------------------------------------------------------------

def tex_scan(text):
    """Yield (index, char) of unescaped, uncommented characters."""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "%":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        yield i, ch
        i += 1


def tex_problems(text, ncols=None):
    problems = []
    depth = 0
    for _, ch in tex_scan(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                problems.append("closing brace without opening")
                depth = 0
        elif ch == "#":
            problems.append("bare #")
    if depth:
        problems.append("unbalanced braces (%d)" % depth)
    for env in set(re.findall(r"\\begin\{(\w+)\}", text)):
        if text.count(r"\begin{%s}" % env) != text.count(r"\end{%s}" % env):
            problems.append("unbalanced environment %s" % env)
    stripped = re.sub(r"\\label\{[^}]*\}", "", text)
    for line in stripped.splitlines():
        if line.startswith("%"):
            continue
        chars = [ch for _, ch in tex_scan(line)]
        if "_" in chars:
            problems.append("bare _ in %r" % line[:80])
        if chars.count("$") % 2:
            problems.append("unbalanced $ in %r" % line[:80])
        if ncols is not None and line.rstrip().endswith("\\\\") and not line.startswith(r"\caption"):
            amps = chars.count("&")
            spans = sum(int(n) - 1 for n in re.findall(r"\\multicolumn\{(\d+)\}", line))
            if amps != ncols - 1 - spans:
                problems.append("%d & (expected %d) in %r" % (amps, ncols - 1 - spans, line[:80]))
    return problems


def build(estimates=None, dataset=None):
    dataset = dataset or synthetic_dataset()
    return tables.build_tables(estimates if estimates is not None else synthetic_estimates(dataset), dataset,
                               METHODOLOGY)


def by_id(built):
    return OrderedDict((t["id"], t) for t in built)


class TablesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = synthetic_dataset()
        cls.estimates = synthetic_estimates(cls.dataset)
        cls.tables = by_id(tables.build_tables(cls.estimates, cls.dataset, METHODOLOGY))

    def refused(self, estimates, pattern):
        with self.assertRaisesRegex(core.AnalysisRefused, pattern):
            tables.build_tables(estimates, self.dataset, METHODOLOGY)

    def find(self, estimates, metric, population, block, strata):
        key = tables.strata_key(strata)
        hits = [e for e in estimates if e["metric_id"] == metric and e["population"] == population
                and e["block"] == block and tables.strata_key(e["strata"]) == key]
        self.assertEqual(len(hits), 1)
        return hits[0]

    def test_every_table_renders_in_all_formats(self):
        self.assertEqual(tuple(self.tables), tables.TABLE_IDS)
        for tid, table in self.tables.items():
            with self.subTest(table=tid):
                self.assertTrue(table["population"] and table["unit"] and table["title"])
                self.assertTrue(table["rows"])
                parsed = list(csv.reader(io.StringIO(tables.table_csv(table).decode("utf-8"))))
                self.assertEqual(parsed[0], [tables.header_text(c) for c in table["columns"]])
                self.assertEqual(len(parsed), len(table["rows"]) + 1)
                self.assertEqual(json.loads(latex.table_json(table).decode("utf-8"))["id"], tid)
                tex = latex.table_tex(table).decode("utf-8")
                self.assertEqual(tex_problems(tex, len(table["columns"])), [])
                for rule in (r"\toprule", r"\midrule", r"\bottomrule"):
                    self.assertIn(rule, tex)
                self.assertNotIn(r"\hline", tex)
                self.assertNotIn("|", "".join(c["align"] for c in table["columns"]))
                self.assertIn(r"\label{tab:study_analysis_001:%s}" % tid, tex)
                self.assertRegex(tex, r"\\caption(\[[^\]]*\])?\{")
                self.assertTrue(tex.startswith("%% Table %s " % tid))
                header_body = tex.split(r"\end{longtable}")[0].split(r"\begin{minipage}")[0]   # without notes
                for footnote in table["footnotes"]:              # no footnote floats unattached
                    if footnote["mark"] == tables.DAGGER:
                        self.assertIn(latex.DAG, header_body, tid)
                        continue
                    self.assertRegex(header_body, r"\\textsuperscript\{([^}]*,)?%s(,[^}]*)?\}" % footnote["mark"],
                                     tid)
                self.assertIn(r"\usepackage{booktabs}", tex.splitlines()[1])
                self.assertIn(r"\usepackage{longtable}", tex.splitlines()[1])

    def test_column_headers_and_keys_unique(self):
        for tid, table in self.tables.items():
            headers = [c["header"] for c in table["columns"]]
            self.assertEqual(len(headers), len(set(headers)), tid)
            self.assertEqual(len(set(c["key"] for c in table["columns"])), len(headers), tid)

    def test_numbers_and_denominators_appear(self):
        q06 = self.find(self.estimates, "Q06", "BASE", "composite", {})
        text = "%.1f (%d/%d)" % (q06["value"] * 100, q06["numerator"], q06["denominator"])
        t2a = self.tables["T2a_initial_quality_composite"]
        self.assertIn(text, tables.table_csv(t2a).decode("utf-8"))
        stacked = r"{@{}r@{}}%.1f\\(%d/%d)\end{tabular}" % (q06["value"] * 100, q06["numerator"], q06["denominator"])
        self.assertIn(stacked, latex.table_tex(t2a).decode("utf-8"))
        ci = "[%.1f, %.1f]" % (q06["ci_low"] * 100, q06["ci_high"] * 100)
        self.assertIn(ci, tables.table_csv(t2a).decode("utf-8"))
        self.assertIn("{%s}" % ci, latex.table_tex(t2a).decode("utf-8"))
        e01 = self.find(self.estimates, "E01", "ENH_PAIRS(BASE)", "composite", {})
        self.assertGreater(e01["denominator"], 999)
        t2d = self.tables["T2d_initial_heldout_composite"]
        self.assertIn("/%s)" % format(e01["denominator"], ",").replace(",", "{,}"),
                      latex.table_tex(t2d).decode("utf-8"))
        self.assertIn("/%d)" % e01["denominator"], tables.table_csv(t2d).decode("utf-8"))
        for table in self.tables.values():
            for row in table["rows"]:
                for column in table["columns"]:
                    raw = row[column["key"]]
                    if column["kind"] in ("rate", "ci", "diff", "ci_pp", "mean") and raw is not None:
                        self.assertIn("denominator", raw)
                        self.assertIsNotNone(raw["denominator"], table["id"])

    def test_repair_table_values_and_signs(self):
        r04 = self.find(self.estimates, "R04", "FINAL", "pilot", {"endpoint": "Q06", "variant": VARIANTS[0]})
        row = [r for r in self.tables["T5_repair_by_model"]["rows"]
               if r["block"] == "pilot" and r["model_id"] == "all" and r["variant"] == VARIANTS[0]][0]
        self.assertEqual(row["gain"]["numerator"], r04["numerator"])
        column = [c for c in self.tables["T5_repair_by_model"]["columns"] if c["key"] == "gain"][0]
        text = tables.cell_text(row["gain"], column)
        self.assertRegex(text, r"^([+-]\d+\.\d|0\.0) \(([+-]?\d+)/%d\)$" % r04["denominator"])
        negative = OrderedDict([("numerator", -12), ("denominator", 396), ("value", -12 / 396.0),
                                ("ci_low", -0.06), ("ci_high", 0.001)])
        self.assertEqual(tables.cell_text(negative, column), "-3.0 (-12/396)")
        self.assertEqual(latex.cell_tex(negative, column),
                         r"\begin{tabular}[t]{@{}r@{}}$-$3.0\\($-$12/396)\end{tabular}")
        ci = tables.col("x", "x", "ci_pp")
        self.assertEqual(latex.cell_tex(negative, ci), "{[$-$6.0, 0.1]}")
        tiny = OrderedDict([("numerator", 0), ("denominator", 5), ("value", -0.0001), ("ci_low", None),
                            ("ci_high", None)])
        self.assertEqual(tables.cell_text(tiny, column), "0.0 (0/5)")

    def test_pilot_footnote_and_marks(self):
        label = METHODOLOGY["reporting"]["pilot_label"]
        for tid, table in self.tables.items():
            blocks = set(r.get("block") for r in table["rows"]) | set(c["key"].split("_")[0] for c in table["columns"])
            has_pilot = "pilot" in blocks or tid in ("T2b_initial_quality_pilot", "T2e_initial_heldout_pilot")
            texts = [f["text"] for f in table["footnotes"]]
            tex = latex.table_tex(table).decode("utf-8")
            if has_pilot:
                self.assertTrue(any(label in t for t in texts), tid)
                self.assertIn(METHODOLOGY["statistics"]["small_cluster_warning"], " ".join(texts))
                self.assertIn(r"\textsuperscript{a}~", tex)
            else:
                self.assertFalse(any(label in t for t in texts), tid)
        t5 = tables.table_csv(self.tables["T5_repair_by_model"]).decode("utf-8")
        self.assertIn("pilot [a]", t5)
        self.assertIn(r"pilot\textsuperscript{a}", latex.table_tex(self.tables["T5_repair_by_model"]).decode())
        self.assertIn("pilot [a]", tables.table_csv(self.tables["T1_inventory"]).decode().splitlines()[0])

    def test_population_unit_and_ci_note_stated(self):
        for tid, table in self.tables.items():
            tex = latex.table_tex(table).decode("utf-8")
            self.assertIn(r"\textit{Population:} " + latex.escape(table["population"]), tex)
            self.assertIn(r"\textit{Unit:} " + latex.escape(table["unit"]), tex)
            has_ci = any(c["kind"] in ("ci", "ci_pp") for c in table["columns"])
            if has_ci:
                self.assertTrue(table["ci_note"], tid)
                self.assertIn(r"\textit{CI:}", tex)
        self.assertIn(format(PRIMARY, ","), self.tables["T9_primary_tests"]["ci_note"])
        self.assertIn(format(DESCRIPTIVE, ","), self.tables["T2a_initial_quality_composite"]["ci_note"])

    def test_longtable_only_for_long_tables(self):
        long_seen = False
        for tid, table in self.tables.items():
            tex = latex.table_tex(table).decode("utf-8")
            two_line = any(c["kind"] in tables.RATIO_KINDS for c in table["columns"])
            self.assertEqual(latex.rendered_lines(table), sum(latex.row_lines(table, r) for r in table["rows"]))
            self.assertTrue(all(latex.row_lines(table, r) == (2 if two_line else 1) or
                                any(c.get("excluded") for c in r.values() if isinstance(c, dict))
                                for r in table["rows"]), tid)
            hinted = bool(table["latex"].get("longtable"))           # tables.LATEX_HINTS (measured: T12)
            self.assertEqual(table["latex"], OrderedDict(tables.LATEX_HINTS.get(tid, ())), tid)
            self.assertEqual(latex.is_long(table), latex.rendered_lines(table) > tables.LONGTABLE_ROWS or hinted)
            if latex.is_long(table):
                long_seen = True
                for marker in (r"\begin{longtable}", r"\endfirsthead", r"\endhead", r"\endfoot", r"\endlastfoot"):
                    self.assertIn(marker, tex, tid)
                self.assertNotIn(r"\begin{table}", tex)
            else:
                self.assertIn(r"\begin{table}[htbp]", tex)
                self.assertIn(r"\begin{tabular}{", tex)
                self.assertNotIn("longtable}", tex.split("\n", 2)[2])
        self.assertTrue(long_seen)
        self.assertIn(r"\begin{longtable}", latex.table_tex(self.tables["T12_addendum"]).decode("utf-8"))
        self.assertIn(r"\scriptsize", latex.table_tex(self.tables["T7c_joint_transitions"]).decode("utf-8")
                      .split(r"\begin{tabular}")[0])

    def test_deterministic_bytes_independent_of_estimate_order(self):
        again = by_id(tables.build_tables(list(reversed(copy.deepcopy(self.estimates))), synthetic_dataset(),
                                          METHODOLOGY))
        for tid in tables.TABLE_IDS:
            for render in (tables.table_csv, tables.table_json, latex.table_tex):
                self.assertEqual(render(self.tables[tid]), render(again[tid]), tid)

    def test_not_stratified_cells_render_dash_with_footnote(self):
        t2d = self.tables["T2d_initial_heldout_composite"]
        full = [r for r in t2d["rows"] if r["model_id"] != "all" and r["execution_model"] != "all"]
        self.assertTrue(full)
        self.assertTrue(all(r["f01"] is None and r["f02"] is None for r in full))
        self.assertTrue(all(r["e04"] is not None for r in t2d["rows"]))        # E04 is estimated per model x em
        self.assertTrue(all(r["f01"] is not None for r in t2d["rows"] if r not in full))
        self.assertIn(tables.NOT_STRATIFIED_MARK, [f["mark"] for f in t2d["footnotes"]])
        self.assertNotIn(tables.NOT_STRATIFIED_MARK,
                         [f["mark"] for f in self.tables["T2a_initial_quality_composite"]["footnotes"]])
        marked = [c["key"] for c in t2d["columns"] if c.get("mark") == tables.NOT_STRATIFIED_MARK]
        self.assertEqual(marked, ["f01", "f02"])                 # the footnote is anchored at the dash columns
        tex = latex.table_tex(t2d).decode("utf-8")
        self.assertIn(" & -- & ", tex)
        self.assertIn(r"\textsuperscript{b}", tex.split(r"\midrule")[0])

    def test_distribution_zero_categories_only_when_complete(self):
        t3 = self.tables["T3_tool_coverage"]
        row = [r for r in t3["rows"] if r["tool"] == "infer" and r["block"] == "pilot"][0]
        self.assertEqual(row["state_TIMEOUT"]["numerator"], 0)
        self.assertEqual(row["state_ABSENT_INAPPLICABLE"]["numerator"], 0)
        self.assertEqual(sum(row["state_" + s]["numerator"] for s in core.TOOL_STATES),
                         row["state_COMPLETED"]["denominator"])
        completed = self.find(self.estimates, "S01", "GENERATED", "pilot", {"tool": "infer", "state": "COMPLETED"})
        self.assertGreater(completed["numerator"], 0)
        broken = [e for e in self.estimates if e is not completed]
        self.assertEqual(len(broken), len(self.estimates) - 1)
        self.refused(broken, "incomplete state distribution")
        mixed = copy.deepcopy(self.estimates)
        [e for e in mixed if e["metric_id"] == "S01" and e["block"] == "pilot" and
         e["strata"] == {"tool": "infer", "state": "PARTIAL"}][0]["denominator"] += 1
        self.refused(mixed, "different denominators")

    def test_r06_status_split_by_iteration_is_summed(self):
        estimates = []
        for e in self.estimates:
            if e["metric_id"] == "R06" and e["block"] == "pilot":
                for k, part in enumerate((e["numerator"] // 2, e["numerator"] - e["numerator"] // 2)):
                    split = copy.deepcopy(e)
                    split["strata"]["step"] = k
                    split["numerator"] = part
                    estimates.append(split)
            else:
                estimates.append(e)
        built = by_id(tables.build_tables(estimates, self.dataset, METHODOLOGY))
        self.assertEqual(tables.table_csv(built["T6_stops_effort"]),
                         tables.table_csv(self.tables["T6_stops_effort"]))

    def test_inventory_counts_from_the_dataset(self):
        t1 = self.tables["T1_inventory"]
        rows = OrderedDict((r["quantity"], r) for r in t1["rows"])
        self.assertEqual([rows["models"][b] for b in BLOCKS], [2, 2, 2])
        self.assertEqual([rows["benchmarks (resampling clusters)"][b] for b in BLOCKS], [4, 12, 16])
        self.assertEqual([rows["base cells (BASE)"][b] for b in BLOCKS], [24, 72, 96])
        self.assertEqual([rows["gated (benchmark, spec, execution model) groups"][b] for b in BLOCKS], [3, 3, 6])
        trajectories = [rows["trajectories (base cells x variants)"][b] for b in BLOCKS]
        self.assertEqual(trajectories, [72, 216, 288])
        statuses = [q for q in rows if q.startswith("terminal status ")]
        self.assertEqual(sum(rows[q]["composite"] for q in statuses), 288)
        bl01 = [q for q in rows if q.startswith("base cells of the BL-01 benchmark")][0]
        self.assertEqual([rows[bl01][b] for b in BLOCKS], [6, 0, 6])
        self.assertFalse(any("owner" in q or "supplemented" in q for q in rows))     # provenance is T1b
        provenance = OrderedDict((r["quantity"], r) for r in self.tables["T1b_provenance"]["rows"])
        self.assertEqual(provenance["static tool entries supplemented by full_ext_recovery_002"]["pilot"], 0)
        self.assertGreater(provenance["static tool entries supplemented by full_ext_recovery_002"]["full_ext"], 0)
        for quantity, row in list(rows.items()) + [(q, r) for q, r in provenance.items() if r["identity"] is None]:
            if quantity not in ("models", "benchmark families (problem types)"):
                self.assertEqual(row["composite"], row["pilot"] + row["full_ext"], quantity)
        summary = tables.summarize_dataset(self.dataset)
        self.assertEqual(summary["counts"], self.dataset.counts())
        self.assertEqual(summary["provenance"]["targets_sha256"], "t" * 8)
        self.assertEqual(by_id(tables.build_tables(self.estimates, summary, METHODOLOGY))["T1_inventory"],
                         t1)

    def test_primary_family_table(self):
        t9 = self.tables["T9_primary_tests"]
        self.assertEqual(len(t9["rows"]), tables.primary_size(METHODOLOGY))
        self.assertEqual([r["endpoint"] for r in t9["rows"]], ["Q06"] * 6 + ["E02"] * 6)
        self.assertEqual([r["metric"] for r in t9["rows"][:6]], ["R04"] * 3 + ["R05"] * 3)
        self.assertEqual(t9["rows"][0]["hypothesis"], "FINAL[%s] - BASE" % VARIANTS[0])
        self.assertEqual(t9["rows"][3]["hypothesis"], "FINAL[%s] - FINAL[%s]" % (VARIANTS[0], VARIANTS[1]))
        self.assertEqual(t9["rows"][5]["hypothesis"], "FINAL[%s] - FINAL[%s]" % (VARIANTS[1], VARIANTS[2]))
        self.assertTrue(all(isinstance(r["reject"], bool) for r in t9["rows"]))
        tex = latex.table_tex(t9).decode("utf-8")
        self.assertIn("yes", tex)

    def test_fail_closed(self):
        est = copy.deepcopy(self.estimates)
        cases = []
        cases.append((est + [copy.deepcopy(est[0])], "duplicate estimate"))
        foreign = copy.deepcopy(est)
        foreign[0]["metric_id"] = "Z99"
        cases.append((foreign, "foreign metric id"))
        bad_block = copy.deepcopy(est)
        bad_block[0]["block"] = "mixed"
        cases.append((bad_block, "foreign block"))
        bad_ci = copy.deepcopy(est)
        bad_ci[0]["ci_method"] = "normal"
        cases.append((bad_ci, "foreign ci_method"))
        missing_field = copy.deepcopy(est)
        del missing_field[0]["note"]
        cases.append((missing_field, "lacks"))
        missing = [e for e in est if not (e["metric_id"] == "Q02" and e["block"] == "pilot" and not e["strata"])]
        cases.append((missing, "missing estimate Q02 BASE pilot"))
        for case, pattern in cases:
            with self.subTest(pattern=pattern):
                self.refused(case, pattern)

    def test_contradictions_refuse(self):
        def mutate(predicate, change):
            est = copy.deepcopy(self.estimates)
            hits = [e for e in est if predicate(e)]
            self.assertTrue(hits)
            for e in hits:
                change(e)
            return est

        r04 = mutate(lambda e: e["metric_id"] == "R04" and e["block"] == "full_ext" and
                     e["strata"] == {"endpoint": "Q06", "variant": VARIANTS[1]},
                     lambda e: e.__setitem__("numerator", e["numerator"] + 1))
        self.refused(r04, "R04 contradicts R02/R03")
        step = mutate(lambda e: e["metric_id"] == "E02" and e["population"] == "STEP" and e["block"] == "pilot" and
                      e["strata"] == {"variant": VARIANTS[0], "step": 0},
                      lambda e: e.__setitem__("numerator", e["numerator"] + 1))
        self.refused(step, "STEP")
        r06 = mutate(lambda e: e["metric_id"] == "R06" and e["block"] == "pilot" and
                     e["strata"]["status"] == "stopped_budget" and e["strata"]["variant"] == VARIANTS[0],
                     lambda e: e.__setitem__("numerator", e["numerator"] + 1))
        self.refused(r06, "R06")
        e04 = mutate(lambda e: e["metric_id"] == "E04" and e["population"] == "ENH_PAIRS(GENERATED)" and
                     e["block"] == "composite", lambda e: e.__setitem__("numerator", e["numerator"] + 1))
        self.refused(e04, "E04")
        family = copy.deepcopy(self.estimates)
        [e for e in family if e["p_holm"] is not None][0].update(p_holm=None, p_resolution=None,
                                                                 p_holm_resolution=None)
        self.refused(family, "primary family has 11")
        swapped = copy.deepcopy(self.estimates)
        r05 = [e for e in swapped if e["p_holm"] is not None and e["metric_id"] == "R05"
               and e["strata"]["endpoint"] == "E02"]
        r05[0]["strata"]["comparison"] = "%s-%s" % (VARIANTS[1], VARIANTS[0])
        r05[1]["strata"]["comparison"] = "%s-%s" % (VARIANTS[0], VARIANTS[1])   # same pair twice, one pair missing
        self.refused(swapped, "primary family for E02 is not")
        replicates = copy.deepcopy(self.estimates)
        [e for e in replicates if e["p_holm"] is not None][0]["replicates"] = DESCRIPTIVE
        self.refused(replicates, "replicates")
        r07 = mutate(lambda e: e["metric_id"] == "R07" and e["block"] == "composite",
                     lambda e: e.__setitem__("numerator", e["numerator"] + 1))
        self.refused(r07, "R07 vs R06")
        ambiguous = copy.deepcopy(self.estimates)
        g01 = copy.deepcopy([e for e in ambiguous if e["metric_id"] == "G01"][0])
        g01["population"] = "BASE"
        ambiguous.append(g01)
        self.refused(ambiguous, "ambiguous estimate G01")

    def test_build_tables_needs_inventory_facts(self):
        with self.assertRaisesRegex(core.AnalysisRefused, "summarize_dataset"):
            tables.build_tables(self.estimates, self.dataset.counts(), METHODOLOGY)

    def test_latex_escaping(self):
        self.assertEqual(latex.escape("a_b & 50% $x# {y} ~ ^ \\ <>|"),
                         r"a\_b \& 50\% \$x\# \{y\} \textasciitilde{} \textasciicircum{} \textbackslash{} "
                         r"\textless{}\textgreater{}\textbar{}")
        self.assertEqual(latex.escape("two\nlines"), "two lines")
        self.assertEqual(latex.tex_number("1,234/1,980"), "1{,}234/1{,}980")
        self.assertEqual(latex.tex_number("12.5 (1,234,567/2,000,000)"), "12.5 (1{,}234{,}567/2{,}000{,}000)")
        self.assertEqual(latex.tex_number("[-1.0, 7.2]"), "{[$-$1.0, 7.2]}")
        self.assertEqual(latex.tex_number("<0.0001"), r"\textless{}0.0001")
        self.assertEqual(latex.tex_number("n=12; p95=3.5"), "n=12; p95=3.5")
        t2 = self.tables["T2a_initial_quality_composite"]
        tex = latex.table_tex(t2).decode("utf-8")
        self.assertIn(r"model\_a", tex)
        self.assertIn(r"{@{}c@{}}Q04\\auto\_closed\end{tabular}", tex)       # long label on two lines
        self.assertIn(r"\% (n/N)", tex)
        self.assertEqual(tex_problems(tex, len(t2["columns"])), [])
        weird = copy.deepcopy(t2)
        weird["title"] = "50% & {braces} #1 under_score ~^\\"
        weird["notes"] = ["$money$ & 100%"]
        weird["rows"][0]["model_id"] = "m&m_{x}"
        self.assertEqual(tex_problems(latex.table_tex(weird).decode("utf-8"), len(t2["columns"])), [])

    def test_group_headers_span_their_columns(self):
        table = self.tables["T5_repair_by_model"]
        lines = latex.header_lines(table["columns"])
        self.assertEqual(len(lines), 3)
        self.assertIn(r"\multicolumn{2}{c}{Q06 correctness pass}", lines[0])
        self.assertIn(r"\cmidrule(lr){4-5}", lines[1])
        self.assertIn(r"\cmidrule(lr){8-9}", lines[1])
        flat = latex.header_lines([tables.col("a", "A_1", "text"), tables.col("b", "B", "count", mark="a")])
        self.assertEqual(flat, [r"A\_1 & B\textsuperscript{a} \\"])

    def test_csv_has_no_thousands_separators(self):
        csv_text = tables.table_csv(self.tables["T2a_initial_quality_composite"]).decode("utf-8")
        self.assertIsNone(re.search(r"\d,\d{3}", csv_text))
        column = tables.col("n", "n", "count")
        self.assertEqual(tables.cell_text(1234567, column), "1234567")
        self.assertEqual(tables.cell_text(1234567, column, sep=True), "1,234,567")
        self.assertEqual(latex.cell_tex(1234567, column), "1{,}234{,}567")
        p = tables.col("p", "p", "p")
        self.assertEqual(tables.cell_text(0.00001, p), "<0.0001")
        self.assertEqual(tables.cell_text(0.04567, p), "0.0457")
        self.assertEqual(tables.cell_text(None, p), "--")

    def test_label_splitting_and_wrapping_columns(self):
        self.assertEqual(latex.split_label("Execution model"), ("Execution", "model"))
        self.assertEqual(latex.split_label("Q04 auto_closed"), ("Q04", "auto_closed"))
        self.assertEqual(latex.split_label("ABSENT_INAPPLICABLE"), ("ABSENT_", "INAPPLICABLE"))
        self.assertIsNone(latex.split_label("% (n/N)"))
        self.assertIsNone(latex.split_label("averyveryverylongword"))
        wrap = tables.col("q", "Quantity", "text", width="2cm")
        self.assertEqual(latex.column_spec(wrap), "l")
        self.assertEqual(latex.cell_tex("a_b+c; d", wrap),
                         r"\parbox[t]{2cm}{\raggedright a\_\allowbreak{}b+\allowbreak{}c;\allowbreak{} d\strut}")
        with self.assertRaisesRegex(core.AnalysisRefused, "bad wrap width"):
            latex.column_spec(tables.col("n", "n", "count", width="2cm"))
        with self.assertRaisesRegex(core.AnalysisRefused, "bad wrap width"):
            latex.column_spec(tables.col("q", "q", "text", width="2cm}{"))

    def test_runtime_rows_pool_and_split_execution_models(self):
        t11 = self.tables["T11_runtime"]
        compiler = [(r["execution_model"], r["block"]) for r in t11["rows"] if r["tool"] == "compiler"]
        self.assertEqual(compiler[:3], [("all", b) for b in BLOCKS])
        self.assertEqual(len(compiler), (1 + len(EXEC)) * len(BLOCKS))
        self.assertTrue(all(r["timeouts"] is not None and r["p95_all"] == 12.25 for r in t11["rows"]))

    def test_heldout_cross_checks_refuse(self):
        def mutated(predicate, key, delta=1):
            est = copy.deepcopy(self.estimates)
            hits = [e for e in est if predicate(e)]
            self.assertEqual(len(hits), 1)
            hits[0][key] += delta
            return est
        self.refused(mutated(lambda e: e["metric_id"] == "G01" and e["block"] == "pilot" and
                             "comparison" in e["strata"] and e["strata"]["variant"] == VARIANTS[2],
                             "reference_numerator"), "G01 reference")
        self.refused(mutated(lambda e: e["metric_id"] == "G02" and e["block"] == "full_ext" and
                             e["strata"] == {"endpoint": "E02", "variant": VARIANTS[1], "step": 1}, "numerator"),
                     "G02 vs E02 STEP")
        foreign = copy.deepcopy(self.estimates)
        [e for e in foreign if e["metric_id"] == "F05"][0]["strata"]["quantity"] = "share"
        self.refused(foreign, "F05 foreign kind / quantity")
        two = copy.deepcopy(self.estimates)
        extra = copy.deepcopy([e for e in two if e["metric_id"] == "G01" and "comparison" in e["strata"]][0])
        extra["strata"]["comparison"] = "G01-other"
        two.append(extra)
        self.refused(two, "expected one difference-to-reference estimate")

    def test_d03_per_execution_model_and_g01_difference(self):
        t8 = self.tables["T8_execution_models"]
        self.assertIn("d03", [c["key"] for c in t8["columns"]])
        self.assertTrue(all(r["d03"] is not None for r in t8["rows"]))
        t7 = self.tables["T7b_heldout_transitions"]
        column = [c for c in t7["columns"] if c["key"] == "g01_diff"][0]
        row = t7["rows"][0]
        self.assertAlmostEqual(row["g01_diff"]["value"], row["g01"]["value"] - row["e05_base"]["value"])
        self.assertRegex(tables.cell_text(row["g01_diff"], column), r"^([+-]\d+\.\d|0\.0)$")


def without(estimates, predicate):
    out = [copy.deepcopy(e) for e in estimates if not predicate(e)]
    assert len(out) < len(estimates), "predicate matched nothing"
    return out


def mutated(estimates, predicate, change):
    out = copy.deepcopy(estimates)
    hits = [e for e in out if predicate(e)]
    assert hits, "predicate matched nothing"
    for e in hits:
        change(e)
    return out


def is_(metric, population=None, block=None, strata=None, **contains):
    """Estimate predicate: metric (+ population, block, exact strata or strata items)."""
    def predicate(e):
        if e["metric_id"] != metric or (population and e["population"] != population) or \
                (block and e["block"] != block):
            return False
        if strata is not None and tables.strata_key(e["strata"]) != tables.strata_key(strata):
            return False
        return all(str(e["strata"].get(k)) == str(v) for k, v in contains.items())
    return predicate


class ReviewFixesTest(unittest.TestCase):
    """Regression tests of the verified review findings (CI statements from
    the replicate counts actually shown, row sets from the dataset, the
    estimate metadata in the cells, required lookups, identical cohorts,
    p-value resolution, anchored footnotes, diagnostic labels)."""

    @classmethod
    def setUpClass(cls):
        cls.dataset = synthetic_dataset()
        cls.estimates = synthetic_estimates(cls.dataset)
        cls.tables = by_id(tables.build_tables(cls.estimates, cls.dataset, METHODOLOGY))

    def refused(self, estimates, pattern, dataset=None):
        with self.assertRaisesRegex(core.AnalysisRefused, pattern):
            tables.build_tables(estimates, dataset or self.dataset, METHODOLOGY)

    def built(self, estimates):
        return by_id(tables.build_tables(estimates, self.dataset, METHODOLOGY))

    # -- finding: CI notes state the replicate counts the shown intervals carry --------------------------------

    def test_ci_note_names_primary_and_descriptive_counts(self):
        primary = "%s replicates for the primary-family estimates (R04 composite with strata endpoint+variant" % (
            format(PRIMARY, ","))
        descriptive = "%s replicates (descriptive, unadjusted)" % format(DESCRIPTIVE, ",")
        for tid in ("T5_repair_by_model", "T5b_repair_by_model_heldout", "T10_sensitivity"):
            note = self.tables[tid]["ci_note"]
            self.assertIn(primary, note, tid)            # the composite all-model R04 rows are primary-family
            self.assertIn(descriptive, note, tid)
        for tid in ("T2a_initial_quality_composite", "T7b_heldout_transitions", "T8_execution_models"):
            self.assertNotIn("primary-family", self.tables[tid]["ci_note"], tid)
        self.assertNotIn(descriptive, self.tables["T9_primary_tests"]["ci_note"])
        row = [r for r in self.tables["T5_repair_by_model"]["rows"]
               if r["block"] == "composite" and r["model_id"] == "all"][0]
        self.assertEqual((row["gain"]["replicates"], row["gain"]["primary"]), (PRIMARY, True))

    def test_interval_with_a_foreign_replicate_count_refuses(self):
        wrong = mutated(self.estimates, is_("R04", "FINAL", "pilot", {"endpoint": "Q06", "variant": VARIANTS[0]}),
                        lambda e: e.__setitem__("replicates", PRIMARY))
        self.refused(wrong, "descriptive interval with 10000 replicates.*not labelled EXPLORATORY")
        missing = mutated(self.estimates, is_("Q06", "BASE", "pilot", {}), lambda e: e.__setitem__("replicates", None))
        self.refused(missing, "without its bootstrap replicate count")
        half = mutated(self.estimates, is_("Q06", "BASE", "pilot", {}), lambda e: e.__setitem__("ci_high", None))
        self.refused(half, "half-open interval")

    def test_exploratory_counts_are_labelled_never_misstated(self):
        label = "EXPLORATORY: 100 bootstrap replicates (methodology %d), not confirmatory" % DESCRIPTIVE

        def explore(e):
            e["replicates"], e["note"] = 100, label
        descriptive = lambda e: e["ci_method"] is not None and e["p_holm"] is None  # noqa: E731
        built = self.built(mutated(self.estimates, descriptive, explore))
        t2a = built["T2a_initial_quality_composite"]
        self.assertTrue(t2a["title"].startswith("EXPLORATORY (not confirmatory): "))
        self.assertIn("100 replicates (descriptive, unadjusted)", t2a["ci_note"])
        self.assertIn("EXPLORATORY", t2a["ci_note"])
        self.assertNotIn(format(DESCRIPTIVE, ",") + " replicates (descriptive", t2a["ci_note"])
        self.assertIn("EXPLORATORY", latex.table_tex(t2a).decode("utf-8").split(r"\label")[0])
        self.assertFalse(built["T1_inventory"]["title"].startswith("EXPLORATORY"))     # no bootstrapped cell
        plain = mutated(self.estimates, descriptive, lambda e: e.__setitem__("replicates", 100))
        self.refused(plain, "not labelled EXPLORATORY")

    def test_degenerate_replicates_are_counted_from_the_note(self):
        note = "3 of %d bootstrap replicates skipped (denominator 0)" % DESCRIPTIVE

        def degenerate(e):
            e["replicates"], e["note"] = DESCRIPTIVE - 3, note
        built = self.built(mutated(self.estimates, is_("Q05", "BASE", "pilot", {}), degenerate))
        self.assertIn("1 interval(s) rest on fewer usable replicates", built["T2b_initial_quality_pilot"]["ci_note"])
        self.assertIn(format(DESCRIPTIVE, ",") + " replicates (descriptive",
                      built["T2b_initial_quality_pilot"]["ci_note"])
        contradiction = mutated(self.estimates, is_("Q05", "BASE", "pilot", {}),
                                lambda e: e.update(replicates=DESCRIPTIVE - 5, note=note))
        self.refused(contradiction, "contradict the note")

    # -- finding: row sets from the dataset / frozen vocabularies, never from the estimates -----------------

    def test_missing_or_extra_models_refuse(self):
        self.refused(without(self.estimates, is_("Q06", "BASE", "pilot", model_id=MODELS[0])),
                     "per-model estimates cover models \\['model_b'\\], the dataset has")
        extra = copy.deepcopy(self.estimates)
        clone = copy.deepcopy([e for e in extra if is_("Q06", "BASE", "pilot", {"model_id": MODELS[0]})(e)][0])
        clone["strata"]["model_id"] = "model_z"
        self.refused(extra + [clone], "per-model estimates cover models")
        self.refused(without(self.estimates, is_("Q06", "BASE", "full_ext", {"execution_model": "omp"})),
                     "per-execution-model estimates cover")

    def test_missing_tools_refuse(self):
        no_infer = without(self.estimates, lambda e: e["metric_id"] in ("S01", "S02") and
                           e["strata"].get("tool") == "infer")
        self.refused(no_infer, "frozen static tool list")
        no_s01 = without(self.estimates, lambda e: e["metric_id"] == "D01" and e["strata"].get("tool") == "must"
                         and e["block"] == "pilot")
        self.refused(no_s01, "D01 GENERATED pilot: tools")

    def test_summary_must_carry_the_expected_row_sets(self):
        summary = tables.summarize_dataset(self.dataset)
        facts = summary["blocks"]["pilot"]
        self.assertEqual(facts["model_ids"], list(MODELS))
        self.assertEqual(facts["execution_models"], list(EXEC))
        self.assertEqual(sum(facts["trajectories_by_variant"].values()), facts["trajectories"])
        self.assertEqual(sum(facts["candidates_by_variant"].values()), sum(facts["candidates"].values()))
        self.assertEqual(list(facts["tools"]["static"]), list(core.STATIC_TOOLS))
        del summary["blocks"]["pilot"]["model_ids"]
        with self.assertRaisesRegex(core.AnalysisRefused, "lacks \\['model_ids'\\]"):
            tables.build_tables(self.estimates, summary, METHODOLOGY)

    # -- finding: estimate metadata (replicates, excluded, note) reaches the cells and the outputs ----------

    def test_cells_carry_replicates_excluded_note_and_source(self):
        cell = [r for r in self.tables["T2b_initial_quality_pilot"]["rows"] if r["model_id"] == "all"
                and r["execution_model"] == "all"][0]["q06"]
        for key in ("replicates", "excluded", "note", "ci_method", "primary", "source"):
            self.assertIn(key, cell)
        self.assertEqual(cell["source"]["metric_id"], "Q06")
        self.assertEqual(cell["replicates"], DESCRIPTIVE)
        self.assertEqual(cell["excluded"], 0)

    def test_excluded_units_are_reported(self):
        predicate = is_("E02", "BASE", "pilot", {"model_id": MODELS[0], "execution_model": "serial"})

        def exclude(e):
            e["denominator"] -= 1
            e["numerator"] = min(e["numerator"], e["denominator"])
            e["value"] = float(e["numerator"]) / e["denominator"]
            e["excluded"] = 1
        built = self.built(mutated(self.estimates, predicate, exclude))
        t2e = built["T2e_initial_heldout_pilot"]
        self.assertIn("; 1 excl.)", tables.table_csv(t2e).decode("utf-8"))
        self.assertIn(r"\1 excl.\end{tabular}", latex.table_tex(t2e).decode("utf-8"))     # LaTeX: own line
        note = [n for n in t2e["notes"] if n.startswith("Denominator exclusions")][0]
        self.assertIn("E02: artifact(s) without a valid pair", note)
        zero = [n for n in self.tables["T2b_initial_quality_pilot"]["notes"] if n.startswith("Denominator")][0]
        self.assertIn("no unit is excluded in this table by Q06 (baseline_incompatible artifact(s))", zero)
        lacking = mutated(self.estimates, is_("Q06", "BASE", "composite", {}), lambda e: e.pop("excluded"))
        self.refused(lacking, "lacks its excluded count")

    # -- finding: lookups required wherever the producer guarantees the estimate -----------------------------

    def test_guaranteed_estimates_are_required(self):
        cases = [
            (without(self.estimates, is_("E04", "ENH_PAIRS(BASE)", "pilot", {"model_id": MODELS[0]})),
             "missing estimate E04 ENH_PAIRS\\(BASE\\) pilot"),
            (without(self.estimates, is_("F05", "BASE", "pilot", tool="gcc_analyzer", family="memory",
                                         kind="non_blocking")), "missing estimate F05 BASE pilot"),
            (without(self.estimates, is_("C03", None, "full_ext", {"variant": VARIANTS[0]})), "T6b: C03"),
            (without(self.estimates, is_("C02", "REPAIR_CANDIDATES", "full_ext",
                                         {"variant": VARIANTS[0], "quantity": "output_tokens"})),
             "sub-quantities differ"),
            (without(self.estimates, is_("F06", None, "pilot", pair="tsan+llov")), "the methodology predefines"),
            (without(self.estimates, is_("C04", None, "pilot", tool="infer")), "ran tool entries imply"),
            (mutated(self.estimates, is_("C04", None, "pilot", tool="infer"),
                     lambda e: e.__setitem__("ran_entries", e["ran_entries"] + 1)), "ran entries, the dataset has"),
            (mutated(self.estimates, is_("E04", "ENH_PAIRS(GENERATED)"), lambda e: e.pop("gated_groups")),
             "lacks gated_groups"),
            (mutated(self.estimates, is_("F06"), lambda e: e.pop("kappa")), "lacks kappa"),
            (mutated(self.estimates, is_("F06"), lambda e: e.pop("positive_agreement")), "lacks positive_agreement"),
            (mutated(self.estimates, lambda e: e["p_holm"] is not None and e["metric_id"] == "R04",
                     lambda e: e.__setitem__("replicates", None)),
             "without a cluster_bootstrap_percentile interval and its replicate count"),
        ]
        for estimates, pattern in cases:
            with self.subTest(pattern=pattern):
                self.refused(estimates, pattern)

    def test_kappa_is_never_replaced_by_overall_agreement(self):
        built = self.built(mutated(self.estimates, is_("F06", None, "pilot", pair="tsan+llov"),
                                   lambda e: e.__setitem__("kappa", None)))
        row = [r for r in built["T4b_tool_agreement"]["rows"] if r["pair"] == "tsan+llov" and r["block"] == "pilot"][0]
        self.assertIsNone(row["kappa"])
        column = [c for c in built["T4b_tool_agreement"]["columns"] if c["key"] == "kappa"][0]
        self.assertEqual(tables.cell_text(row["kappa"], column), "--")

    # -- low findings: cohorts, p resolution, T4 denominators, labels, anchors ---------------------------------

    def test_identical_cohort_is_checked(self):
        predicate = is_("Q06", "FINAL", "pilot", {"variant": VARIANTS[1]})
        shrunk = mutated(self.estimates, predicate, lambda e: e.update(
            denominator=e["denominator"] - 3, numerator=min(e["numerator"], e["denominator"] - 3)))
        self.refused(shrunk, "not the identical cohort")
        last = STEPS[-1]                     # FINAL[v] == STEP[v][last] == G02 (T7a): change all three alike
        explained = mutated(self.estimates, lambda e: predicate(e) or is_(
            "Q06", "STEP", "pilot", {"variant": VARIANTS[1], "step": last})(e) or is_(
            "G02", "STEP", "pilot", {"endpoint": "Q06", "variant": VARIANTS[1], "step": last})(e),
            lambda e: e.update(denominator=e["denominator"] - 3, numerator=min(e["numerator"], e["denominator"] - 3),
                               excluded=3))
        q06 = [e for e in explained if predicate(e)][0]
        for e in explained:                    # X04 rests on the Q06-failing artifacts of the same population
            if is_("X04", "FINAL", "pilot", variant=VARIANTS[1])(e):
                e["denominator"] = q06["denominator"] - q06["numerator"]
                e["numerator"] = min(e["numerator"], e["denominator"] // 2)
                e["value"] = float(e["numerator"]) / e["denominator"]
                e["ci_low"], e["ci_high"] = e["value"] - 0.05, e["value"] + 0.04
        t5 = self.built(explained)["T5_repair_by_model"]
        self.assertIn("; 3 excl.)", tables.table_csv(t5).decode("utf-8"))
        step = mutated(self.estimates, is_("E02", "STEP", "full_ext", {"variant": VARIANTS[2], "step": 1}),
                       lambda e: e.__setitem__("denominator", e["denominator"] + 2))
        for e in step:                                             # keep G02 == E02 STEP
            if is_("G02", None, "full_ext", {"endpoint": "E02", "variant": VARIANTS[2], "step": 1})(e):
                e["denominator"] += 2
        self.refused(step, "E02 STEP\\[combined_feedback\\]\\[1\\] vs BASE \\(full_ext\\): not the identical cohort")

    def test_zero_p_is_shown_at_the_bootstrap_resolution(self):
        target = lambda e: e["p_holm"] is not None and e["metric_id"] == "R04"  # noqa: E731
        first = [e for e in self.estimates if target(e)][0]
        zero = mutated(self.estimates, lambda e: e is not None and target(e) and
                       tables.strata_key(e["strata"]) == tables.strata_key(first["strata"]),
                       lambda e: e.update(p_value=0.0, p_holm=0.0))
        t9 = self.built(zero)["T9_primary_tests"]
        text = tables.table_csv(t9).decode("utf-8")
        resolution = "<%s" % ("%.8f" % (2.0 / PRIMARY)).rstrip("0")
        holm = "<%s" % ("%.8f" % (12 * 2.0 / PRIMARY)).rstrip("0")
        row = [r for r in csv.reader(io.StringIO(text))][1 + [i for i, r in enumerate(t9["rows"])
                                                               if r["p_value"]["value"] == 0.0][0]]
        self.assertEqual(row[5:7], [resolution, holm])             # <0.0002 and the Holm resolution <0.0024
        self.assertEqual(holm, "<0.0024" if PRIMARY == 10000 else holm)
        self.assertNotIn("<0.0001", text)
        self.assertTrue(any("2/B" in n for n in t9["notes"]))
        fields = OrderedDict((f["field"], f["rule"]) for f in ADDENDUM["estimate_fields"])
        self.assertTrue(any(fields["p_holm_resolution"] in n for n in t9["notes"]))
        self.assertEqual(tables.primary_size(METHODOLOGY), len(t9["rows"]))

    def test_findings_cells_carry_the_artifact_denominator(self):
        t4 = self.tables["T4_findings"]
        row = [r for r in t4["rows"] if r["tool"] == "gcc_analyzer" and r["block"] == "pilot"][0]
        est = [e for e in self.estimates if is_("F05", "BASE", "pilot", tool="gcc_analyzer", family="memory",
                                                kind="reported_blocking", quantity="artifacts_with_finding")(e)][0]
        self.assertEqual(row["BASE_reported_blocking"][1:], [est["numerator"], est["denominator"]])
        column = [c for c in t4["columns"] if c["key"] == "BASE_reported_blocking"][0]
        self.assertRegex(tables.cell_text(row["BASE_reported_blocking"], column),
                         r"^\d+ \(%d/%d\)$" % (est["numerator"], est["denominator"]))
        dash = [c for c in t4["columns"] if c["key"] == "BASE_low_confidence"][0]
        self.assertEqual(dash.get("mark"), tables.OMITTED_MARK)       # the tsan rows have no such finding

    def test_diagnostic_populations_are_labelled(self):
        for tid in ("T3_tool_coverage", "T4_findings", "T4b_tool_agreement", "T6b_effort", "T11_runtime"):
            text = self.tables[tid]["population"] + " ".join(self.tables[tid]["notes"])
            self.assertIn("diagnostic", self.tables[tid]["population"], tid)
            self.assertIn("diagnostic only", text, tid)

    def test_single_block_pilot_tables_anchor_the_pilot_mark_at_the_caption(self):
        for tid in ("T2b_initial_quality_pilot", "T2e_initial_heldout_pilot"):
            tex = latex.table_tex(self.tables[tid]).decode("utf-8")
            caption = [l for l in tex.splitlines() if l.startswith(r"\caption")][0]
            self.assertIn(r"\textsuperscript{a}}", caption, tid)
            self.assertTrue(caption.startswith(r"\caption[%s]" % latex.escape(self.tables[tid]["title"])))
        tex = latex.table_tex(self.tables["T2a_initial_quality_composite"]).decode("utf-8")
        self.assertIn(r"\caption{%s}" % latex.escape(self.tables["T2a_initial_quality_composite"]["title"]), tex)


def degenerate(e):
    """Make an estimate's interval zero-width (every supporting cluster at the boundary)."""
    e["ci_low"] = e["ci_high"] = e["value"]
    e["ci_degenerate"] = True


def notes_text(table):
    return " ".join(table["notes"] + [f["text"] for f in table["footnotes"]])


class AddendumRoundTest(unittest.TestCase):
    """DESIGN2 section 2 (fix round 2): contract keys, degenerate intervals,
    addendum notes, the split / new tables and their cross-checks."""

    @classmethod
    def setUpClass(cls):
        cls.dataset = synthetic_dataset()
        cls.estimates = synthetic_estimates(cls.dataset)
        cls.tables = by_id(tables.build_tables(cls.estimates, cls.dataset, METHODOLOGY))

    def refused(self, estimates, pattern, addendum=None):
        with self.assertRaisesRegex(core.AnalysisRefused, pattern):
            tables.build_tables(estimates, self.dataset, METHODOLOGY, addendum=addendum)

    def built(self, estimates, addendum=None):
        return by_id(tables.build_tables(estimates, self.dataset, METHODOLOGY, addendum=addendum))

    # -- section 1 contract keys --------------------------------------------------------------------------------

    def test_contract_keys_are_required_and_checked(self):
        for key in tables.CONTRACT_FIELDS:
            with self.subTest(key=key):
                self.refused(mutated(self.estimates, is_("Q02", "BASE", "pilot", {}), lambda e, k=key: e.pop(k)),
                             "lacks \\['%s'\\]" % key)
        self.refused(mutated(self.estimates, is_("Q06", "BASE", "pilot", {}),
                             lambda e: e.__setitem__("post_freeze", True)), "post_freeze True")
        self.refused(mutated(self.estimates, is_("X04", "BASE", "pilot", {"state": "CLEAN_COMPLETE"}),
                             lambda e: e.__setitem__("post_freeze", False)), "post_freeze False")
        self.refused(mutated(self.estimates, is_("Q06", "BASE", "pilot", {}),
                             lambda e: e.__setitem__("ci_degenerate", True)), "ci_degenerate True contradicts")
        self.refused(mutated(self.estimates, is_("Q02", "BASE", "pilot", {}),
                             lambda e: e.__setitem__("ci_degenerate", False)), "ci_degenerate False without")
        self.refused(mutated(self.estimates, is_("Q06", "BASE", "pilot", {}),
                             lambda e: e.__setitem__("p_resolution", 0.0002)), "outside the primary family")
        primary = lambda e: e["p_holm"] is not None  # noqa: E731
        first = [e for e in self.estimates if primary(e)][0]
        self.refused(mutated(self.estimates, lambda e: e is not None and primary(e) and
                             tables.strata_key(e["strata"]) == tables.strata_key(first["strata"]),
                             lambda e: e.__setitem__("p_holm_resolution", 2.0 / PRIMARY)), "p_holm_resolution")
        self.refused(mutated(self.estimates, primary, lambda e: e.__setitem__("p_resolution", 1.0 / PRIMARY)),
                     "p_resolution")
        self.refused([e for e in self.estimates] + [dict(copy.deepcopy(self.estimates[0]), metric_id="X99")],
                     "foreign metric id 'X99'")

    # -- item 1: degenerate intervals ---------------------------------------------------------------------------

    def test_degenerate_intervals_carry_the_dagger_and_the_note(self):
        built = self.built(mutated(self.estimates, is_("Q06", "BASE", "pilot", {}), degenerate))
        t2b = built["T2b_initial_quality_pilot"]
        q06 = self.find_cell(t2b, "q06_ci")
        self.assertTrue(q06["ci_degenerate"])
        text = tables.table_csv(t2b).decode("utf-8")
        shown = "[%.1f, %.1f]" % (q06["ci_low"] * 100, q06["ci_high"] * 100)
        self.assertIn(shown + tables.DAGGER, text)
        self.assertEqual(text.count(tables.DAGGER), 1)                 # only the degenerate interval is marked
        self.assertEqual([f["text"] for f in t2b["footnotes"] if f["mark"] == tables.DAGGER],
                         [NOTES["DEGENERATE_CI"]])
        tex = latex.table_tex(t2b).decode("utf-8")
        self.assertIn("{%s}%s" % (shown, latex.DAG), tex)
        self.assertIn(latex.DAG + "~" + latex.escape(NOTES["DEGENERATE_CI"]), tex)
        self.assertEqual(tex_problems(tex, len(t2b["columns"])), [])
        self.assertIn("1 interval(s) of zero width", t2b["ci_note"])
        for tid, table in self.tables.items():                         # no zero-width interval in the fixture
            self.assertNotIn(tables.DAGGER, tables.table_csv(table).decode("utf-8"), tid)
            self.assertNotIn(NOTES["DEGENERATE_CI"], notes_text(table), tid)
        # every shown CI is marked exactly when it is degenerate
        for tid, table in built.items():
            for row in table["rows"]:
                for c in table["columns"]:
                    if c["kind"] in tables.CI_KINDS and row[c["key"]] is not None:
                        marked = tables.cell_text(row[c["key"]], c).endswith(tables.DAGGER)
                        self.assertEqual(marked, bool(row[c["key"]]["ci_degenerate"]), tid)

    def find_cell(self, table, key, **match):
        rows = [r for r in table["rows"] if all(r.get(k) == v for k, v in match.items())]
        return rows[0][key]

    # -- item 2: notes from the addendum ------------------------------------------------------------------------

    def test_addendum_notes_are_placed_by_rule(self):
        bl01 = set(tid for tid, t in self.tables.items() if NOTES["BL01"] in notes_text(t))
        for tid in ("T2a_initial_quality_composite", "T2b_initial_quality_pilot", "T2d_initial_heldout_composite",
                    "T2e_initial_heldout_pilot", "T5_repair_by_model", "T5b_repair_by_model_heldout",
                    "T7a_heldout_rates", "T7b_heldout_transitions", "T7c_joint_transitions", "T8_execution_models",
                    "T9_primary_tests", "T9b_primary_by_block", "T10_sensitivity", "T12_addendum"):
            self.assertIn(tid, bl01)
        for tid in ("T1_inventory", "T1b_provenance", "T2c_initial_quality_full_ext", "T2f_initial_heldout_full_ext",
                    "T3_tool_coverage", "T4_findings", "T4b_tool_agreement", "T6_stops_effort", "T11_runtime",
                    "T12b_dirty_checks", "T12c_iterations_to_clean"):
            self.assertNotIn(tid, bl01)
        reasoning = set(tid for tid, t in self.tables.items() if NOTES["REASONING"] in notes_text(t))
        self.assertEqual(reasoning, set(tables.TABLE_IDS[2:8]) | {"T5_repair_by_model", "T5b_repair_by_model_heldout"})
        states = set(tid for tid, t in self.tables.items() if NOTES["EFFECTIVE_STATES"] in notes_text(t))
        self.assertEqual(states, {"T3_tool_coverage"})
        caveat = lambda cid: set(tid for tid, t in self.tables.items() if CAVEATS[cid] in notes_text(t))  # noqa
        # IC3 names G01 and the split T7_heldout: only the part showing G01 carries it
        self.assertIn("T7b_heldout_transitions", caveat("IC3"))
        self.assertFalse({"T7a_heldout_rates", "T7c_joint_transitions"} & caveat("IC3"))
        self.assertTrue({"T9_primary_tests", "T9b_primary_by_block", "T10_sensitivity"} <= caveat("IC5"))
        self.assertTrue({"T10_sensitivity", "T2a_initial_quality_composite"} <= caveat("IC7"))     # Q04 / Q10 / X01
        self.assertTrue({"T2d_initial_heldout_composite", "T8_execution_models", "T12_addendum",
                         "T12b_dirty_checks"} <= caveat("IC4"))
        self.assertNotIn("T1_inventory", caveat("IC1"))
        self.assertTrue(any(n.startswith("BL01: " + NOTES["BL01"]) for n in self.tables["T5_repair_by_model"]["notes"]))

    def test_notes_come_from_the_addendum(self):
        changed = copy.deepcopy(ADDENDUM)
        for note in changed["table_notes"]:
            note["text"] = "CHANGED " + note["text"]
        for caveat in changed["interpretive_caveats"]:
            caveat["text"] = "CHANGED " + caveat["text"]
        built = self.built(self.estimates, changed)
        self.assertIn("CHANGED " + NOTES["BL01"], notes_text(built["T5_repair_by_model"]))
        self.assertIn("CHANGED " + CAVEATS["IC5"], notes_text(built["T9_primary_tests"]))
        missing = copy.deepcopy(ADDENDUM)
        missing["table_notes"] = [n for n in missing["table_notes"] if n["id"] != "REASONING"]
        self.refused(self.estimates, "lacks the table note\\(s\\) \\['REASONING'\\]", missing)
        foreign = copy.deepcopy(ADDENDUM)
        foreign["interpretive_caveats"][0]["applies_to"].append("T99_nothing")
        self.refused(self.estimates, "unknown table / figure 'T99_nothing'", foreign)
        typo = copy.deepcopy(ADDENDUM)
        typo["interpretive_caveats"][0]["applies_to"].append("Q6")
        self.refused(self.estimates, "unknown applies_to 'Q6'", typo)
        unplaced = copy.deepcopy(ADDENDUM)
        unplaced["table_notes"].append(OrderedDict([("id", "NEW"), ("applies_to", "somewhere"), ("text", "x")]))
        self.refused(self.estimates, "names no table / figure and no known rule", unplaced)
        split = copy.deepcopy(ADDENDUM)              # a split id without metrics covers every part
        split["interpretive_caveats"].append(OrderedDict([("id", "IC9"), ("applies_to", ["T7_heldout"]),
                                                          ("text", "SPLIT CAVEAT")]))
        split["table_notes"].append(OrderedDict([("id", "NEW"), ("applies_to", "T1_inventory and T12b_dirty_checks"),
                                                 ("text", "LISTED NOTE")]))
        built = self.built(self.estimates, split)
        self.assertEqual(set(t for t in built if "IC9: SPLIT CAVEAT" in built[t]["notes"]),
                         {"T7a_heldout_rates", "T7b_heldout_transitions", "T7c_joint_transitions"})
        self.assertEqual(set(t for t in built if "NEW: LISTED NOTE" in built[t]["notes"]),
                         {"T1_inventory", "T12b_dirty_checks"})

    def test_post_freeze_tables_are_labelled(self):
        prefix = "POST-FREEZE (addendum_1, descriptive): "
        for tid in ("T7c_joint_transitions", "T12_addendum", "T12b_dirty_checks", "T12c_iterations_to_clean"):
            self.assertTrue(self.tables[tid]["title"].startswith(prefix), tid)
        for tid in ("T10_sensitivity", "T7c_joint_transitions", "T12_addendum", "T12b_dirty_checks",
                    "T12c_iterations_to_clean"):
            post = [n for n in self.tables[tid]["notes"] if n.startswith("POST-FREEZE (%s" % ADDENDUM["addendum_id"])]
            self.assertEqual(len(post), 1, tid)
        self.assertIn("X01 paired_auto_closed_sensitivity", " ".join(self.tables["T10_sensitivity"]["notes"]))
        self.assertFalse(any(n.startswith("POST-FREEZE") for n in self.tables["T9_primary_tests"]["notes"]))
        cell_ = self.tables["T10_sensitivity"]["rows"][0]["x01"]
        self.assertTrue(cell_["post_freeze"])
        self.assertFalse(self.tables["T10_sensitivity"]["rows"][0]["main"]["post_freeze"])

    # -- items 3-5: T1 / T6 / T7 splits -------------------------------------------------------------------------

    def test_t1b_provenance_identities(self):
        t1b = self.tables["T1b_provenance"]
        identities = [r for r in t1b["rows"] if r["identity"] is not None]
        self.assertEqual([r["quantity"] for r in identities][:2],
                         ["dataset input targets_sha256", "dataset input census_digest"])
        self.assertEqual(identities[-2]["identity"], tables.canonical_sha256(METHODOLOGY))
        self.assertEqual(identities[-1]["identity"], tables.canonical_sha256(ADDENDUM))
        self.assertEqual(tables.canonical_sha256(METHODOLOGY), ADDENDUM["amends"]["methodology_canonical_sha256"])
        self.assertTrue(all(r[b] is None for r in identities for b in BLOCKS))
        tex = latex.table_tex(t1b).decode("utf-8")
        sha = identities[-1]["identity"]
        self.assertIn(sha[:16] + r"\allowbreak{}" + sha[16:32], tex)
        self.assertIn(sha, tables.table_csv(t1b).decode("utf-8"))

    def test_t6_r09_header_and_t6b_population_abbreviation(self):
        t6 = self.tables["T6_stops_effort"]
        r09 = [c for c in t6["columns"] if c["key"] == "r09"][0]
        self.assertEqual(r09["header"], "R09 >=1 repair requested % (n/N)")
        meaning = OrderedDict((m["id"], m) for m in METHODOLOGY["metrics"])["R09"]["meaning"]
        self.assertTrue(any(meaning in n for n in t6["notes"]))
        self.assertTrue(any(n.startswith("R07 equals the R06 stopped_budget share") for n in t6["notes"]))
        self.assertIn(r"\textgreater{}=1 repair\\requested", latex.table_tex(t6).decode("utf-8"))
        t6b = self.tables["T6b_effort"]
        self.assertIn("REPAIR_CANDIDATES", [r["population"] for r in t6b["rows"]])      # raw value kept (JSON)
        csv_text = tables.table_csv(t6b).decode("utf-8")
        self.assertIn(",REPAIR_CAND.,", csv_text)
        self.assertNotIn(",REPAIR_CANDIDATES,", csv_text)
        self.assertIn("REPAIR_CAND. = REPAIR_CANDIDATES", " ".join(t6b["notes"]))
        self.assertIn('"population": "REPAIR_CANDIDATES"', tables.table_json(t6b).decode("utf-8"))

    def test_t7_split_and_x06_crosstab(self):
        t7a, t7b, t7c = (self.tables[t] for t in ("T7a_heldout_rates", "T7b_heldout_transitions",
                                                  "T7c_joint_transitions"))
        self.assertEqual([c["key"] for c in t7a["columns"]],
                         ["block", "variant", "e01_base", "e01_final"] + ["e02_step%d" % k for k in STEPS]
                         + ["q06_step%d" % k for k in STEPS])
        self.assertEqual(len(t7a["rows"]), len(BLOCKS) * len(VARIANTS))
        self.assertEqual(len(t7b["rows"]), len(BLOCKS) * len(VARIANTS))
        self.assertIn("e02_improved", [c["key"] for c in t7b["columns"]])
        self.assertEqual(len(t7c["rows"]), len(VARIANTS) * 4)
        self.assertEqual([r["q06"] for r in t7c["rows"]][:4],
                         ["not_pass->pass", "pass->not_pass", "not_pass->not_pass", "pass->pass"])
        for v in VARIANTS:
            rows = [r for r in t7c["rows"] if r["variant"] == v]
            total = sum(r["total"]["numerator"] for r in rows)
            self.assertEqual(total, rows[0]["total"]["denominator"])
        self.refused(without(self.estimates, is_("X06", "FINAL", "composite", variant=VARIANTS[0],
                                                 transition="pass->pass", heldout_transition="all_pass->all_pass")),
                     "X06 FINAL composite static_feedback: transitions")
        self.refused(mutated(self.estimates, is_("X06", "FINAL", "composite", variant=VARIANTS[1],
                                                 transition="pass->pass", heldout_transition="all_pass->all_pass"),
                             lambda e: e.__setitem__("numerator", e["numerator"] + 1)), "not a partition")
        q06_step = [r for r in t7a["rows"] if r["block"] == "pilot" and r["variant"] == VARIANTS[0]][0]["q06_step0"]
        self.assertEqual(q06_step["source"]["metric_id"], "G02")
        self.refused(mutated(self.estimates, is_("G02", "STEP", "pilot", {"endpoint": "Q06", "variant": VARIANTS[0],
                                                                          "step": 1}),
                             lambda e: e.__setitem__("numerator", e["numerator"] + 1)), "G02 vs Q06 STEP")

    def test_json_keeps_strata_types(self):
        data = json.loads(tables.table_json(self.tables["T7a_heldout_rates"]).decode("utf-8"))
        steps = [r["e02_step1"]["source"]["strata"]["step"] for r in data["rows"]]
        self.assertTrue(all(isinstance(s, int) and s == 1 for s in steps))
        x05 = json.loads(tables.table_json(self.tables["T12c_iterations_to_clean"]).decode("utf-8"))
        self.assertIsInstance(x05["rows"][0]["it2"]["source"]["strata"]["iteration"], int)

    # -- item 6: T9 / T9b ---------------------------------------------------------------------------------------

    def test_t9b_primary_hypotheses_per_block(self):
        t9b = self.tables["T9b_primary_by_block"]
        t9 = self.tables["T9_primary_tests"]
        self.assertEqual([r["hypothesis"] for r in t9b["rows"]], [r["hypothesis"] for r in t9["rows"]])
        self.assertEqual([c["key"] for c in t9b["columns"]][3:],
                         [k for b in BLOCKS[:2] for k in (b, b + "_ci")])          # composite = T9
        self.assertEqual([c.get("mark") for c in t9b["columns"] if c["key"] == "pilot"], [tables.PILOT_MARK])
        for row, primary in zip(t9b["rows"], t9["rows"]):
            self.assertFalse(row["pilot"]["primary"] or row["full_ext"]["primary"])
            self.assertEqual(row["pilot"]["numerator"] + row["full_ext"]["numerator"], primary["estimate"]["numerator"])
        self.assertIn(METHODOLOGY["statistics"]["small_cluster_warning"], notes_text(t9b))
        self.assertIn(CAVEATS["IC5"], notes_text(t9b))
        self.assertIn("%s replicates (descriptive" % format(DESCRIPTIVE, ","), t9b["ci_note"])
        self.assertNotIn("primary-family", t9b["ci_note"])
        self.refused(mutated(self.estimates, is_("R05", "FINAL", "pilot", {"endpoint": "E02",
                                                                         "comparison": "%s-%s" % VARIANTS[:2]}),
                             lambda e: e.__setitem__("numerator", e["numerator"] + 1)), "do not add up")
        self.refused(mutated(self.estimates, is_("R04", "FINAL", "pilot", {"endpoint": "Q06", "variant": VARIANTS[0]}),
                             lambda e: e.__setitem__("p_value", 0.5)), "carries a test")

    # -- item 7: T10 --------------------------------------------------------------------------------------------

    def test_t10_rows_sa1_x01_and_q10(self):
        t10 = self.tables["T10_sensitivity"]
        self.assertEqual(len(t10["rows"]), len(BLOCKS) * 2 * 6)
        self.assertEqual(set(r["endpoint"] for r in t10["rows"]), {"Q06", "E02"})
        e02 = [r for r in t10["rows"] if r["endpoint"] == "E02" and r["block"] == "pilot"]
        self.assertTrue(all(r["sa1"] is not None and r["x01"] is not None for r in e02))
        self.assertTrue(all(r["sa1"]["source"]["strata"]["sensitivity"] == "SA1" for r in e02))
        r05 = [r for r in t10["rows"] if r["main"]["source"]["metric_id"] == "R05"]
        self.assertEqual(len(r05), len(BLOCKS) * 2 * 3)
        self.assertTrue(all(r["r02"] is None and r["q10_final"] is None for r in r05))
        self.assertTrue(all(r["q10_final"] is not None for r in t10["rows"]
                            if r["endpoint"] == "Q06" and r["main"]["source"]["metric_id"] == "R04"))
        self.assertIn("; 4 excl.)", tables.table_csv(t10).decode("utf-8"))           # X01 removed cells
        self.assertIn(tables.COHORT_MARK, [f["mark"] for f in t10["footnotes"]])
        self.assertIn(CAVEATS["IC7"], notes_text(t10))
        self.refused(mutated(self.estimates, is_("X01", "FINAL", "full_ext", {"endpoint": "E02",
                                                                            "variant": VARIANTS[2]}),
                             lambda e: e.__setitem__("excluded", 5)), "X01 vs R04 full_ext E02")
        self.refused(without(self.estimates, is_("R05", "FINAL", "pilot", {"endpoint": "E02", "sensitivity": "SA1",
                                                                         "comparison": "%s-%s" % VARIANTS[:2]})),
                     "missing estimate R05")
        self.refused(mutated(self.estimates, is_("X01", "FINAL", "pilot", {"endpoint": "Q06", "variant": VARIANTS[0]}),
                             lambda e: e.pop("excluded")), "X01 .* lacks its excluded count")

    # -- item 8: T12 / T12b -------------------------------------------------------------------------------------

    def test_t12_addendum_cross_checks(self):
        t12 = self.tables["T12_addendum"]
        self.assertEqual(len(t12["rows"]), len(BLOCKS) * (1 + len(VARIANTS)))
        for row in t12["rows"]:
            self.assertEqual(row["x02"]["numerator"], row["f01"]["numerator"] - row["x02_only"]["numerator"])
            self.assertEqual(row["x04_clean"]["denominator"], row["x04_nfi"]["denominator"])
        t12c = self.tables["T12c_iterations_to_clean"]
        self.assertEqual(len(t12c["rows"]), len(BLOCKS) * len(VARIANTS))
        for row in t12c["rows"]:
            dist = [row["it%d" % k]["numerator"] for k in STEPS]
            self.assertEqual(row["mean"]["numerator"], sum(k * n for k, n in zip(STEPS, dist)))
            self.assertEqual(sum(dist), row["mean"]["denominator"])
        self.refused(mutated(self.estimates, is_("X02", "BASE", "pilot", {"state": "DIRTY"}),
                             lambda e: e.__setitem__("dirty_only_under_frozen_rule",
                                                     e["dirty_only_under_frozen_rule"] + 1)), "X02 vs F01 pilot BASE")
        self.refused(mutated(self.estimates, is_("X02", "FINAL", "full_ext", {"state": "DIRTY",
                                                                            "variant": VARIANTS[1]}),
                             lambda e: e.pop("dirty_only_under_frozen_rule")), "lacks its count")
        self.refused(mutated(self.estimates, is_("X05", "TRAJECTORIES", "composite", {"variant": VARIANTS[0]}),
                             lambda e: e.__setitem__("numerator", e["numerator"] + 1)), "X05 composite")
        self.refused(without(self.estimates, is_("X04", "FINAL", "pilot", {"variant": VARIANTS[2],
                                                                         "state": "NO_FINDING_INCOMPLETE"})),
                     "missing estimate X04")

    def test_t12b_dirty_checks(self):
        t12b = self.tables["T12b_dirty_checks"]
        tools_ = [r["tool"] for r in t12b["rows"] if r["check_id"].startswith("(any check)")]
        self.assertEqual(tools_, list(core.STATIC_ANALYSIS_TOOLS))
        clang = [r for r in t12b["rows"] if r["tool"] == "clang_tidy" and not r["check_id"].startswith("(")]
        counts = [r["composite_findings"] for r in clang]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(set(r["check_id"] for r in clang), set(X03_CHECKS["clang_tidy"]))
        self.assertTrue(all(r["composite_findings"] == r["pilot_findings"] + r["full_ext_findings"] for r in clang))
        self.refused(without(self.estimates, is_("X03", "BASE", "pilot", {"tool": "cppcheck", "check_id": "nullPointer",
                                                                        "quantity": "artifacts_with_check"})),
                     "X03 pilot cppcheck artifacts_with_check: check ids")
        self.refused(mutated(self.estimates, is_("X03", "BASE", "full_ext", {"tool": "infer",
                                                                           "quantity": "dirty_only_via_tool"}),
                             lambda e: e.__setitem__("denominator", e["denominator"] + 1)),
                     "dirty-only denominator")

    # -- items 11 / 12: preamble, layout, ids -----------------------------------------------------------------------

    def test_preamble_and_layout(self):
        preamble = latex.preamble_tex().decode("utf-8")
        for package in (r"\usepackage[T1]{fontenc}", r"\usepackage{booktabs}", r"\usepackage{longtable}",
                        r"\usepackage{pdflscape}", r"\usepackage{pgfplots}", r"\pgfplotsset{compat=1.18}"):
            self.assertIn(package, preamble)
        self.assertIn("lscape", preamble.split(r"\usepackage{pdflscape}")[1].splitlines()[0])
        self.assertEqual(tuple(latex.LAYOUT), tables.TABLE_IDS)
        self.assertTrue(set(latex.LAYOUT.values()) <= set(latex.LAYOUT_TEXT))
        for tid in tables.TABLE_IDS:
            self.assertIn(tid, preamble)
            tex = latex.table_tex(self.tables[tid]).decode("utf-8")
            self.assertTrue(tex.splitlines()[2].startswith("% Layout: "), tid)
        self.assertEqual(tex_problems(preamble), [])
        self.assertEqual(tables.TABLE_IDS, tuple(self.tables))
        for tid in ("T1b_provenance", "T7a_heldout_rates", "T7b_heldout_transitions", "T7c_joint_transitions",
                    "T9b_primary_by_block", "T12_addendum", "T12b_dirty_checks", "T12c_iterations_to_clean"):
            self.assertIn(tid, tables.TABLE_IDS)
        self.assertNotIn("T7_heldout", tables.TABLE_IDS)


class ReviewRound3Test(unittest.TestCase):
    """Regression tests of the verified review findings of fix round 2:
    IC6 placement by variant, exact applies_to ids, the X01 / X06 / X04 / X03
    cohort ties, the T9 drawn replicate count and the explicit addendum."""

    @classmethod
    def setUpClass(cls):
        cls.dataset = synthetic_dataset()
        cls.estimates = synthetic_estimates(cls.dataset)
        cls.tables = by_id(tables.build_tables(cls.estimates, cls.dataset, METHODOLOGY))

    def refused(self, estimates, pattern, addendum=None):
        with self.assertRaisesRegex(core.AnalysisRefused, pattern):
            tables.build_tables(estimates, self.dataset, METHODOLOGY, addendum=addendum)

    def built(self, estimates, addendum=None):
        return by_id(tables.build_tables(estimates, self.dataset, METHODOLOGY, addendum=addendum))

    # -- IC6: a variant token attaches to every result of that variant ----------------------------------------

    def test_ic6_on_every_static_feedback_result(self):
        carrying = set(tid for tid, t in self.tables.items() if CAVEATS["IC6"] in notes_text(t))
        self.assertEqual(carrying, {
            "T5_repair_by_model", "T5b_repair_by_model_heldout", "T6_stops_effort", "T6b_effort",
            "T7a_heldout_rates", "T7b_heldout_transitions", "T7c_joint_transitions", "T8_execution_models",
            "T9_primary_tests", "T9b_primary_by_block", "T10_sensitivity", "T12_addendum",
            "T12c_iterations_to_clean"})
        for tid in carrying:                                   # once per table, never duplicated
            self.assertEqual(sum(1 for n in self.tables[tid]["notes"] if n.startswith("IC6: ")), 1, tid)

    def test_variant_tokens_match_strata_variant_and_comparison_labels(self):
        added = copy.deepcopy(ADDENDUM)
        added["interpretive_caveats"].append(OrderedDict([("id", "IC9"), ("applies_to", [VARIANTS[1]]),
                                                          ("text", "VARIANT CAVEAT")]))
        disclosure = tables.disclosure_for(METHODOLOGY, added)

        def hit(strata):
            source = OrderedDict([("metric_id", "R05"), ("block", "full_ext"), ("strata", strata)])
            return "IC9" in [cid for cid, _ in disclosure.apply("T1_inventory", [source])]
        self.assertTrue(hit({"endpoint": "E02", "comparison": "%s-%s" % (VARIANTS[1], VARIANTS[2])}))
        self.assertFalse(hit({"endpoint": "E02", "comparison": "%s-%s" % (VARIANTS[0], VARIANTS[2])}))
        self.assertTrue(hit({"endpoint": "E02", "variant": VARIANTS[1]}))
        self.assertFalse(hit({"endpoint": "E02", "variant": VARIANTS[2]}))
        # a variant name counts only as a whole token of the comparison label
        self.assertEqual(tables.variants_of({"strata": {"comparison": "x%s-%s" % (VARIANTS[1], VARIANTS[0])}},
                                            VARIANTS), {VARIANTS[0]})
        built = self.built(self.estimates, added)
        self.assertIn("IC9: VARIANT CAVEAT", built["T9_primary_tests"]["notes"])
        self.assertNotIn("IC9: VARIANT CAVEAT", built["T2a_initial_quality_composite"]["notes"])

    def test_applies_to_ids_are_exact_or_declared_splits(self):
        for good, bad in (("T10_sensitivity", "T10_sensitivty"), ("T9b_primary_by_block", "T9_primary_by_blok")):
            typo = copy.deepcopy(ADDENDUM)
            for caveat in typo["interpretive_caveats"]:
                caveat["applies_to"] = [bad if token == good else token for token in caveat["applies_to"]]
            self.refused(self.estimates, "unknown table / figure '%s'" % bad, typo)
        note_typo = copy.deepcopy(ADDENDUM)
        for note in note_typo["table_notes"]:
            note["applies_to"] = note["applies_to"].replace("T3_tool_coverage", "T3_tool_coverag")
        self.refused(self.estimates, "unknown table / figure 'T3_tool_coverag'", note_typo)
        split = copy.deepcopy(ADDENDUM)
        split["interpretive_caveats"].append(OrderedDict([("id", "IC9"), ("applies_to", ["T2_initial_quality"]),
                                                          ("text", "T2 CAVEAT")]))
        built = self.built(self.estimates, split)
        self.assertEqual(set(t for t in built if "IC9: T2 CAVEAT" in built[t]["notes"]),
                         set(tables.SPLIT_IDS["T2_initial_quality"]))

    # -- X01: one cohort per (block, endpoint) ------------------------------------------------------------------

    def test_x01_cohort_is_one_per_block_and_endpoint(self):
        def shift(e):                          # 3 cells moved from the denominator to the excluded count
            e["denominator"] -= 3
            e["excluded"] += 3
        self.refused(mutated(self.estimates, is_("X01", "FINAL", "pilot", {"endpoint": "Q06", "variant": VARIANTS[0]}),
                             shift), "X01 pilot Q06: the auto-closed cohort differs between the variants")
        self.refused(mutated(self.estimates, is_("X01", "FINAL", "composite", {
            "endpoint": "E02", "comparison": "%s-%s" % VARIANTS[1:]}), shift),
            "X01 composite E02: the auto-closed cohort differs")
        every = mutated(self.estimates, is_("X01", "FINAL", "full_ext", endpoint="E02"), shift)
        rows = [r for r in self.built(every)["T10_sensitivity"]["rows"]
                if r["block"] == "full_ext" and r["endpoint"] == "E02"]
        self.assertEqual(len(rows), 6)
        self.assertEqual(set((r["x01"]["denominator"], r["x01"]["excluded"]) for r in rows),
                         {(cells_of("full_ext", {}) - 7, 7)})

    # -- X06: the cells of both paired cohorts, marginals within R01 ---------------------------------------------

    def test_x06_cohort_is_tied_to_the_paired_cohorts_and_r01(self):
        def scaled(e):
            e["numerator"] *= 1000
            e["denominator"] *= 1000
            e["value"] = float(e["numerator"]) / e["denominator"]
        self.refused(mutated(self.estimates, is_("X06", "FINAL", "composite"), scaled),
                     "X06 FINAL composite static_feedback: a cohort of 96000 cells")
        x06 = [e for e in self.estimates if is_("X06", "FINAL", "composite", variant=VARIANTS[1])(e)]
        donor = max(x06, key=lambda e: e["numerator"])
        taker = [e for e in x06 if e["strata"]["heldout_transition"] == donor["strata"]["heldout_transition"]
                 and e["strata"]["transition"] != donor["strata"]["transition"]][0]
        moved = mutated(self.estimates, is_("X06", "FINAL", "composite", donor["strata"]),
                        lambda e: e.__setitem__("numerator", e["numerator"] - 1))
        moved = mutated(moved, is_("X06", "FINAL", "composite", taker["strata"]),
                        lambda e: e.__setitem__("numerator", e["numerator"] + 1))
        self.refused(moved, "X06 FINAL composite test_feedback: [0-9]+ cells with the Q06 transition")
        t7c = self.tables["T7c_joint_transitions"]
        for v in VARIANTS:                    # the fixture's rows reproduce the R01 Q06 counts
            for row in [r for r in t7c["rows"] if r["variant"] == v]:
                r01 = self.find_r01(v, row["q06"])
                self.assertEqual(row["total"]["numerator"], r01["numerator"])
        self.assertIn("within the R01 Q06 / E02 transition counts (checked)", " ".join(t7c["notes"]))

    def find_r01(self, variant, label):
        return [e for e in self.estimates if is_("R01", "FINAL", "composite", {
            "endpoint": "Q06", "variant": variant, "transition": label})(e)][0]

    # -- X04: the Q06-failing artifacts ----------------------------------------------------------------------------

    def test_x04_denominator_is_the_q06_failing_artifacts(self):
        def wider(e):
            e["denominator"] += 50
            e["value"] = float(e["numerator"]) / e["denominator"]
        self.refused(mutated(self.estimates, is_("X04", "BASE", "pilot"), wider), "X04 pilot BASE: denominator")
        self.refused(mutated(self.estimates, is_("X04", "FINAL", "composite", variant=VARIANTS[2]), wider),
                     "X04 composite FINAL\\[combined_feedback\\]: denominator")
        self.refused(mutated(self.estimates, is_("X04", "FINAL", "full_ext", variant=VARIANTS[0]),
                             lambda e: e.__setitem__("numerator", e["denominator"])), "count more artifacts")
        for row in self.tables["T12_addendum"]["rows"]:
            population, strata = (("BASE", {}) if row["population"] == "BASE" else
                                  ("FINAL", {"variant": row["population"][len("FINAL["):-1]}))
            q06 = [e for e in self.estimates if is_("Q06", population, row["block"], strata)(e)][0]
            self.assertEqual(row["x04_clean"]["denominator"], q06["denominator"] - q06["numerator"])

    # -- X03: shape, tool set, top-N, applicable denominators ---------------------------------------------------

    def test_x03_shape_selection_and_denominators(self):
        self.assertEqual(tables.x03_top(ADDENDUM), 10)
        first = X03_CHECKS["clang_tidy"][0]
        extra = copy.deepcopy(self.estimates)
        for e in [e for e in self.estimates if is_("X03", "BASE", None, tool="clang_tidy", check_id=first)(e)]:
            for i in range(12):
                twin = copy.deepcopy(e)
                twin["strata"]["check_id"] = "extra-check-%02d" % i
                extra.append(twin)
        self.refused(extra, "X03 clang_tidy: 15 check ids, the addendum selects the top 10 per tool")
        compiler = copy.deepcopy(self.estimates)
        twin = copy.deepcopy([e for e in compiler if is_("X03", "BASE", "pilot", tool="cppcheck",
                                                         quantity=tables.X03_DIRTY_ONLY)(e)][0])
        twin["strata"]["tool"] = "compiler"
        self.refused(compiler + [twin], "X03 pilot \\{quantity=dirty_only_via_tool, tool=compiler\\}: a tool outside")
        shape = copy.deepcopy(twin)
        shape["strata"] = OrderedDict([("tool", "cppcheck"), ("quantity", "other")])
        self.refused(self.estimates + [shape], "X03 estimate BASE pilot with strata")

        def plus(n):
            def change(e):
                e["denominator"] += n
                e["value"] = float(e["numerator"]) / e["denominator"]
            return change
        self.refused(mutated(self.estimates, is_("X03", "BASE", "pilot", tool="clang_tidy", check_id=first,
                                                 quantity=tables.X03_ARTIFACTS), plus(7)),
                     "X03 pilot clang_tidy artifacts_with_check: denominators \\[24, 31\\]")
        self.refused(mutated(self.estimates, is_("X03", "BASE", "full_ext", tool="clang_tidy",
                                                 quantity=tables.X03_ARTIFACTS), plus(1)),
                     "X03 full_ext clang_tidy artifacts_with_check: denominators \\[73\\], .* \\(S02 BASE\\) are 72")
        silent = copy.deepcopy(ADDENDUM)
        for m in silent["metrics"]:
            if m["id"] == "X03":
                m["meaning"] = m["meaning"].replace("the 10 check ids", "the top check ids")
        self.refused(self.estimates, "does not state one check-id count", silent)

    # -- T9: the drawn replicate count ------------------------------------------------------------------------------

    def test_t9_replicate_note_uses_the_drawn_count(self):
        first = [e for e in self.estimates if e["p_holm"] is not None][0]

        def skip(e):
            e["replicates"] = PRIMARY - 10
            e["note"] = "10 of %d bootstrap replicates skipped" % PRIMARY
        t9 = self.built(mutated(self.estimates, lambda e: e["p_holm"] is not None and e["metric_id"] == first[
            "metric_id"] and tables.strata_key(e["strata"]) == tables.strata_key(first["strata"]), skip))[
            "T9_primary_tests"]
        self.assertFalse(t9["title"].startswith(tables.EXPLORATORY))
        self.assertFalse(any(tables.EXPLORATORY in n for n in t9["notes"]))
        drawn = format(PRIMARY, ",")
        self.assertTrue(any(n.startswith("Every hypothesis rests on the methodology's primary replicate count "
                                         "(B = %s drawn" % drawn) for n in t9["notes"]))
        self.assertTrue(any(n.startswith("Resolution (B = %s replicates;" % drawn) for n in t9["notes"]))
        self.assertIn("1 interval(s) rest on fewer usable replicates", t9["ci_note"])

    # -- an explicitly passed addendum ----------------------------------------------------------------------------

    def test_explicit_addendum_is_checked(self):
        from thesis.study_analysis import figures
        cases = []
        for key, value in (("status", "DRAFT"), ("schema_version", "study_analysis_methodology_addendum.v0")):
            bad = copy.deepcopy(ADDENDUM)
            bad[key] = value
            cases.append((bad, "not a study_analysis_methodology_addendum\\.v1 addendum with status"))
        other = copy.deepcopy(ADDENDUM)
        other["amends"]["methodology_canonical_sha256"] = "0" * 64
        cases.append((other, "amends another methodology"))
        collide = copy.deepcopy(ADDENDUM)
        collide["metrics"][0]["id"] = "Q06"
        cases.append((collide, "collide with frozen ids"))
        for addendum, pattern in cases:
            with self.subTest(pattern=pattern):
                self.refused(self.estimates, pattern, addendum)
                with self.assertRaisesRegex(core.AnalysisRefused, pattern):
                    figures.build_figures(self.estimates, METHODOLOGY, self.dataset, addendum=addendum)
        self.assertEqual(self.built(self.estimates, copy.deepcopy(ADDENDUM)), self.tables)


class ProducerIntegrationTest(unittest.TestCase):
    """The real producer (metrics.compute) on the synthetic dataset of
    test_metrics: the tables and figures must accept its estimates as they
    are (contract between the two modules)."""

    def test_metrics_output_renders(self):
        try:
            from thesis.study_analysis import figures, metrics
            from thesis.study_analysis.test_metrics import synthetic_dataset as metrics_dataset
        except ImportError as exc:                                     # module not present yet
            self.skipTest("metrics.py / test_metrics.py not importable: %s" % exc)
        dataset = metrics_dataset()
        estimates = metrics.compute(dataset, METHODOLOGY)        # the methodology's replicate counts (~1 s here)
        built = by_id(tables.build_tables(estimates, dataset, METHODOLOGY))
        self.assertEqual(tuple(built), tables.TABLE_IDS)
        for tid, table in built.items():
            self.assertEqual(tex_problems(latex.table_tex(table).decode("utf-8"), len(table["columns"])), [], tid)
        self.assertEqual(len(built["T9_primary_tests"]["rows"]), tables.primary_size(METHODOLOGY))
        drawn = figures.build_figures(estimates, METHODOLOGY)
        self.assertEqual(tuple(f["id"] for f in drawn), figures.FIGURE_IDS)
        self.assertEqual(figures.build_figures(estimates, METHODOLOGY, dataset), drawn)
        # the composite all-model R04 rows are the producer's primary-family estimates (10,000 replicates)
        self.assertIn("%s replicates for the primary-family estimates" % format(
            int(METHODOLOGY["statistics"]["bootstrap"]["replicates_primary"]), ","),
            built["T5_repair_by_model"]["ci_note"])
        # an exploratory producer run is labelled in every table / figure that shows its intervals
        exploratory = metrics.compute(dataset, METHODOLOGY, bootstrap_descriptive=100, exploratory=True)
        again = by_id(tables.build_tables(exploratory, dataset, METHODOLOGY))
        self.assertTrue(again["T2a_initial_quality_composite"]["title"].startswith("EXPLORATORY"))
        self.assertIn("100 replicates", again["T2a_initial_quality_composite"]["ci_note"])
        f1 = figures.build_figures(exploratory, METHODOLOGY, dataset)[0]
        self.assertTrue(f1["title"].startswith("EXPLORATORY"))
        self.assertIn("100 replicates", " ".join(f1["notes"]))


if __name__ == "__main__":
    unittest.main()
