"""Tests of the study figures (figures.py) on the synthetic estimates of
test_tables: valid SVG (xml.etree), self-contained pgfplots code that carries
the data points, CSV data, determinism and fail-closed lookups.

    python3 -B -m unittest -v thesis.study_analysis.test_figures
"""
from __future__ import annotations

import copy
import csv
import io
import re
import unittest
import xml.etree.ElementTree as ET
from collections import OrderedDict

from thesis.study_analysis import core, figures, latex
from thesis.study_analysis.tables import DAGGER
from thesis.study_analysis.test_tables import (ADDENDUM, METHODOLOGY, MODELS, VARIANTS, degenerate,
                                               synthetic_dataset, synthetic_estimates, tex_problems)

SVG_NS = "{http://www.w3.org/2000/svg}"


def by_id(built):
    return OrderedDict((f["id"], f) for f in built)


class FiguresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.estimates = synthetic_estimates(synthetic_dataset())
        cls.figures = by_id(figures.build_figures(cls.estimates, METHODOLOGY))

    def find(self, metric, population, block, strata):
        hits = [e for e in self.estimates if e["metric_id"] == metric and e["population"] == population
                and e["block"] == block and dict(e["strata"]) == strata]
        self.assertEqual(len(hits), 1)
        return hits[0]

    def test_ids_and_shapes(self):
        self.assertEqual(tuple(self.figures), figures.FIGURE_IDS)
        for fid, fig in self.figures.items():
            with self.subTest(figure=fid):
                self.assertEqual(tuple(fig), figures.FIGURE_KEYS)
                self.assertTrue(fig["data_rows"] and fig["notes"] and fig["title"])
                parsed = list(csv.reader(io.StringIO(figures.figure_csv(fig).decode("utf-8"))))
                self.assertEqual(parsed[0], fig["data_columns"])
                self.assertEqual(len(parsed), len(fig["data_rows"]) + 1)
        self.assertEqual(len(self.figures["F1_correctness_before_after"]["data_rows"]), 3 * (1 + len(VARIANTS)))
        self.assertEqual(len(self.figures["F3_heatmap_model_variant"]["data_rows"]), len(MODELS) * len(VARIANTS))
        self.assertEqual(len(self.figures["F4_tool_states"]["data_rows"]),
                         len(core.STATIC_TOOLS + core.DYNAMIC_TOOLS) * len(core.TOOL_STATES))

    def test_svg_is_valid_xml_with_viewbox_and_legend(self):
        for fid, fig in self.figures.items():
            with self.subTest(figure=fid):
                root = ET.fromstring(figures.figure_svg(fig))
                self.assertEqual(root.tag, SVG_NS + "svg")
                self.assertRegex(root.get("viewBox"), r"^0 0 \d+ \d+$")
                self.assertEqual(root.find(SVG_NS + "title").text, fig["title"])
                texts = [t.text for t in root.iter(SVG_NS + "text")]
                self.assertIn(fig["title"], texts)
                sizes = [int(t.get("font-size")) for t in root.iter(SVG_NS + "text")]
                self.assertGreaterEqual(min(sizes), 10)
                if fid != "F3_heatmap_model_variant":
                    for label in (VARIANTS if fid != "F4_tool_states" else fig["axes"]["states"]):
                        self.assertTrue(any(t and label in t for t in texts), label)
                tips = [t.text for t in root.iter(SVG_NS + "title")][1:]
                self.assertTrue(tips)

    def test_svg_carries_the_data(self):
        q06 = self.find("Q06", "BASE", "composite", {})
        svg = figures.figure_svg(self.figures["F1_correctness_before_after"]).decode("utf-8")
        self.assertIn("composite, BASE: %.1f%% (%d/%d)" % (q06["value"] * 100, q06["numerator"], q06["denominator"]),
                      svg)
        r04 = self.find("R04", "FINAL", "composite", {"endpoint": "Q06", "variant": VARIANTS[1], "model_id": MODELS[0]})
        heat = figures.figure_svg(self.figures["F3_heatmap_model_variant"]).decode("utf-8")
        self.assertIn(figures._gain_text(r04["value"] * 100), heat)

    def test_pgfplots_self_contained_with_data_points(self):
        for fid, fig in self.figures.items():
            with self.subTest(figure=fid):
                tex = figures.figure_pgfplots(fig).decode("utf-8")
                head = tex.splitlines()[:3]
                self.assertTrue(any(r"\usepackage{pgfplots}" in line for line in head))
                self.assertTrue(any(r"\pgfplotsset{compat=1.18}" in line for line in head))
                self.assertTrue(all(line.startswith("%") for line in head))
                for env in ("tikzpicture", "axis"):
                    self.assertEqual(tex.count(r"\begin{%s}" % env), 1)
                    self.assertEqual(tex.count(r"\end{%s}" % env), 1)
                self.assertEqual(tex_problems(tex), [])
                for forbidden in (r"\input", r"\include", r"\addplot table", "table {", r"\usepgfplotslibrary"):
                    self.assertNotIn(forbidden, tex)
                self.assertIn("coordinates {", tex)
                self.assertIn("xlabel={", tex)
                self.assertIn("ylabel={", tex)
                if fid != "F3_heatmap_model_variant":
                    self.assertIn(r"\addlegendentry{", tex)
        f1 = figures.figure_pgfplots(self.figures["F1_correctness_before_after"]).decode("utf-8")
        q06 = self.find("Q06", "BASE", "composite", {})
        pct = q06["value"] * 100
        self.assertIn("(2,%s) += (0,%s) -= (0,%s)" % (figures._c(pct), figures._c(q06["ci_high"] * 100 - pct),
                                                     figures._c(pct - q06["ci_low"] * 100)), f1)
        f2_fig = self.figures["F2_heldout_over_iterations"]
        f2 = figures.figure_pgfplots(f2_fig).decode("utf-8")
        step = self.find("E02", "STEP", "composite", {"variant": VARIANTS[2], "step": 1})
        dodge = [s["dodge"] for s in f2_fig["axes"]["series"] if s["endpoint"] == "E02"
                 and s["variant"] == VARIANTS[2]][0]
        self.assertIn("(%s,%s)" % (figures._c(1 + dodge), figures._c(step["value"] * 100)), f2)
        self.assertEqual([r["step"] for r in f2_fig["data_rows"]][:3], [0, 1, 2])   # the CSV keeps integer steps
        self.assertIn("dashed", f2)
        f3 = figures.figure_pgfplots(self.figures["F3_heatmap_model_variant"]).decode("utf-8")
        r04 = self.find("R04", "FINAL", "composite", {"endpoint": "Q06", "variant": VARIANTS[0], "model_id": MODELS[1]})
        self.assertIn("{%s}" % latex.tex_number(figures._gain_text(r04["value"] * 100)), f3)
        self.assertNotRegex(f3, r"\{-\d")                      # minus signs are math minus, never hyphens
        self.assertIn(r"{model\_a}", f3)
        f4 = figures.figure_pgfplots(self.figures["F4_tool_states"]).decode("utf-8")
        completed = self.find("S01", "GENERATED", "composite", {"tool": "compiler", "state": "COMPLETED"})
        self.assertIn("(0,%s)" % figures._c(completed["value"] * 100), f4)
        self.assertIn(r"\addlegendentry{NOT\_APPLICABLE}", f4)
        self.assertNotIn(r"\addlegendentry{TIMEOUT}", f4)          # zero everywhere -> no series
        f5 = figures.figure_pgfplots(self.figures["F5_gain_vs_effort"]).decode("utf-8")
        tokens = self.find("C02", "REPAIR_CANDIDATES", "composite",
                           {"variant": VARIANTS[0], "model_id": MODELS[0], "quantity": "output_tokens"})
        gain = self.find("R04", "FINAL", "composite",
                         {"endpoint": "Q06", "variant": VARIANTS[0], "model_id": MODELS[0]})
        self.assertIn("(%s,%s)" % (figures._c(tokens["numerator"] / 1e6), figures._c(gain["value"] * 100)), f5)

    def test_deterministic_bytes(self):
        again = by_id(figures.build_figures(list(reversed(copy.deepcopy(self.estimates))), METHODOLOGY))
        for fid in figures.FIGURE_IDS:
            for render in (figures.figure_csv, figures.figure_pgfplots, figures.figure_svg):
                self.assertEqual(render(self.figures[fid]), render(again[fid]), fid)

    def test_missing_value_is_skipped_not_invented(self):
        estimates = copy.deepcopy(self.estimates)
        target = [e for e in estimates if e["metric_id"] == "Q06" and e["population"] == "FINAL"
                  and e["block"] == "pilot" and dict(e["strata"]) == {"variant": VARIANTS[0]}][0]
        # every final artifact excluded (identical cohort: denominator + excluded = the base cells)
        target.update(numerator=0, excluded=target["denominator"], denominator=0, value=None, ci_low=None,
                      ci_high=None, ci_method=None, replicates=None, ci_degenerate=None)
        fig = by_id(figures.build_figures(estimates, METHODOLOGY))["F1_correctness_before_after"]
        row = [r for r in fig["data_rows"] if r["block"] == "pilot" and r["series"] == VARIANTS[0]][0]
        self.assertIsNone(row["value_pct"])
        tex = figures.figure_pgfplots(fig).decode("utf-8")
        line = [l for l in tex.splitlines() if l.startswith(r"\addplot") and "saSeriesB" in l][0]
        self.assertIn("coordinates {(1,", line)          # the pilot group (x = 0) has no bar
        ET.fromstring(figures.figure_svg(fig))
        self.assertIn(",,,", figures.figure_csv(fig).decode("utf-8").splitlines()[2])

    def test_heat_colors_diverge_around_gray(self):
        self.assertEqual(figures.heat_color(0.0, 10.0), figures.MIDPOINT)
        self.assertEqual(figures.heat_color(10.0, 10.0), figures.GAIN)
        self.assertEqual(figures.heat_color(-20.0, 10.0), figures.LOSS)
        self.assertEqual(figures.heat_color(None, 10.0), figures.MISSING)
        self.assertEqual(figures.text_on(figures.GAIN), "white")
        self.assertEqual(figures.text_on(figures.MIDPOINT), "black")

    def test_nice_ticks(self):
        ticks, step = figures.nice_ticks(0.0, 100.0)
        self.assertEqual((ticks[0], ticks[-1], step), (0.0, 100.0, 20.0))
        ticks, step = figures.nice_ticks(-3.2, 7.9)
        self.assertLessEqual(ticks[0], -3.2)
        self.assertGreaterEqual(ticks[-1], 7.9)
        self.assertEqual(step, 2.5)
        ticks, _ = figures.nice_ticks(0.0, 0.0)
        self.assertLess(ticks[0], ticks[-1])

    def test_fail_closed(self):
        no_tokens = [e for e in self.estimates if not (e["metric_id"] == "C02" and e["block"] == "composite"
                                                       and e["strata"].get("model_id") == MODELS[0])]
        with self.assertRaisesRegex(core.AnalysisRefused, "C02 output tokens"):
            figures.build_figures(no_tokens, METHODOLOGY)
        step = copy.deepcopy(self.estimates)
        [e for e in step if e["metric_id"] == "Q06" and e["population"] == "STEP" and e["block"] == "composite"
         and dict(e["strata"]) == {"variant": VARIANTS[1], "step": 2}][0]["numerator"] += 1
        with self.assertRaisesRegex(core.AnalysisRefused, "F2: Q06 STEP"):
            figures.build_figures(step, METHODOLOGY)
        missing = [e for e in self.estimates if not (e["metric_id"] == "Q06" and e["population"] == "BASE"
                                                     and e["block"] == "full_ext" and not e["strata"])]
        with self.assertRaisesRegex(core.AnalysisRefused, "missing estimate Q06 BASE full_ext"):
            figures.build_figures(missing, METHODOLOGY)
        with self.assertRaisesRegex(core.AnalysisRefused, "unknown figure kind"):
            figures.figure_svg(OrderedDict([("kind", "pie")]))

    def test_bar_without_interval_gets_no_whisker(self):
        estimates = copy.deepcopy(self.estimates)
        target = [e for e in estimates if e["metric_id"] == "Q06" and e["population"] == "FINAL"
                  and e["block"] == "pilot" and dict(e["strata"]) == {"variant": VARIANTS[0]}][0]
        target.update(ci_low=None, ci_high=None, ci_method=None, replicates=None, ci_degenerate=None)
        fig = by_id(figures.build_figures(estimates, METHODOLOGY))["F1_correctness_before_after"]
        tex = figures.figure_pgfplots(fig).decode("utf-8")
        self.assertNotIn("+= (0,0.000) -= (0,0.000)", tex)
        plots = [l for l in tex.splitlines() if l.startswith(r"\addplot")]
        bar = [l for l in plots if "fill=saSeriesB" in l][0]
        whisker = plots[plots.index(bar) + 1]
        self.assertIn("forget plot, draw=none", whisker)
        self.assertIn("coordinates {(0,", bar)                  # the bar is drawn ...
        self.assertNotIn("{(0,", whisker)                       # ... without a whisker
        shift = re.search(r"bar shift=([-0-9.]+pt)", bar).group(1)
        self.assertIn("bar shift=%s," % shift, whisker)         # whiskers sit on their bars
        self.assertNotIn("error bars", bar)
        self.assertEqual(len([l for l in plots if "fill=sa" in l]), 1 + len(VARIANTS))
        svg = figures.figure_svg(fig).decode("utf-8")
        ET.fromstring(svg)

    def test_interval_note_states_the_carried_replicates(self):
        descriptive = int(METHODOLOGY["statistics"]["bootstrap"]["replicates_descriptive"])
        f1 = self.figures["F1_correctness_before_after"]
        self.assertIn("%s replicates (descriptive, unadjusted)" % format(descriptive, ","), f1["notes"][1])
        self.assertTrue(all(r["replicates"] == descriptive for r in f1["data_rows"]))
        self.assertIn("replicates", f1["data_columns"])
        self.assertIn("excluded", figures.figure_csv(f1).decode("utf-8").splitlines()[0])
        self.assertTrue(any("replicates" in n for n in self.figures["F3_heatmap_model_variant"]["notes"]))
        label = "EXPLORATORY: 100 bootstrap replicates (methodology %d), not confirmatory" % descriptive
        exploratory = copy.deepcopy(self.estimates)
        for e in exploratory:
            if e["ci_method"] is not None and e["p_holm"] is None:
                e["replicates"], e["note"] = 100, label
        drawn = by_id(figures.build_figures(exploratory, METHODOLOGY))
        self.assertTrue(drawn["F1_correctness_before_after"]["title"].startswith("EXPLORATORY"))
        self.assertIn("100 replicates", drawn["F1_correctness_before_after"]["notes"][1])
        for e in exploratory:
            if e["note"] == label:
                e["note"] = None
        with self.assertRaisesRegex(core.AnalysisRefused, "not labelled EXPLORATORY"):
            figures.build_figures(exploratory, METHODOLOGY)

    def test_rows_never_come_from_whichever_estimates_exist(self):
        no_infer = [e for e in self.estimates if not (e["metric_id"] in ("S01", "S02")
                                                      and e["strata"].get("tool") == "infer")]
        with self.assertRaisesRegex(core.AnalysisRefused, "frozen static tool list"):
            figures.build_figures(no_infer, METHODOLOGY)
        no_model = [e for e in self.estimates if not (e["block"] == "composite" and e["metric_id"] in ("Q01", "R04")
                                                      and e["strata"].get("model_id") == MODELS[0])]
        with self.assertRaisesRegex(core.AnalysisRefused, "a model is missing"):
            figures.build_figures(no_model, METHODOLOGY)
        with self.assertRaisesRegex(core.AnalysisRefused, "the dataset has"):
            figures.build_figures(no_model, METHODOLOGY, synthetic_dataset())
        r04 = [e for e in self.estimates if not (e["block"] == "composite" and e["metric_id"] == "R04"
                                                 and e["strata"].get("model_id") == MODELS[1]
                                                 and e["strata"].get("variant") == VARIANTS[2])]
        with self.assertRaisesRegex(core.AnalysisRefused, "R04 Q06 combined_feedback covers models"):
            figures.build_figures(r04, METHODOLOGY)
        self.assertEqual(figures.build_figures(self.estimates, METHODOLOGY, synthetic_dataset()),
                         list(self.figures.values()))

    def test_identical_cohort_is_checked(self):
        estimates = copy.deepcopy(self.estimates)
        target = [e for e in estimates if e["metric_id"] == "Q06" and e["population"] == "FINAL"
                  and e["block"] == "pilot" and dict(e["strata"]) == {"variant": VARIANTS[1]}][0]
        target["denominator"] -= 3
        with self.assertRaisesRegex(core.AnalysisRefused, "F1: Q06 FINAL\\[test_feedback\\] vs BASE \\(pilot\\): "
                                                          "not the identical cohort"):
            figures.build_figures(estimates, METHODOLOGY)
        step = copy.deepcopy(self.estimates)
        [e for e in step if e["metric_id"] == "E02" and e["population"] == "STEP" and e["block"] == "composite"
         and dict(e["strata"]) == {"variant": VARIANTS[0], "step": 1}][0]["denominator"] += 1
        with self.assertRaisesRegex(core.AnalysisRefused, "F2: E02 STEP\\[static_feedback\\]\\[1\\] vs BASE"):
            figures.build_figures(step, METHODOLOGY)

    def test_colors_follow_the_entity(self):
        f1 = self.figures["F1_correctness_before_after"]["axes"]
        f5 = self.figures["F5_gain_vs_effort"]["axes"]
        self.assertEqual(f1["colors"][1:], f5["colors"])
        f2 = self.figures["F2_heldout_over_iterations"]["axes"]["series"]
        self.assertEqual([s["color"] for s in f2 if s["endpoint"] == "Q06"], f5["colors"])
        self.assertEqual(len(set(re.findall(r"#[0-9a-f]{6}", " ".join(f5["colors"])))), len(VARIANTS))


class FiguresRoundTest(unittest.TestCase):
    """DESIGN2 section 2 item 9: legends and pilot tick, F2 range and error
    bars, F3 colorbar and bold cells, F4 diagnostic label, F5 log axis and
    point labels, wrapped SVG captions, caption files, addendum notes,
    degenerate intervals."""

    @classmethod
    def setUpClass(cls):
        cls.estimates = synthetic_estimates(synthetic_dataset())
        cls.figures = by_id(figures.build_figures(cls.estimates, METHODOLOGY))

    def built(self, estimates):
        return by_id(figures.build_figures(estimates, METHODOLOGY))

    def test_f1_legend_final_and_pilot_tick(self):
        f1 = self.figures["F1_correctness_before_after"]
        self.assertEqual(f1["axes"]["legend"], ["BASE"] + ["FINAL[%s]" % v for v in VARIANTS])
        tex = figures.figure_pgfplots(f1).decode("utf-8")
        self.assertIn(r"\addlegendentry{FINAL[%s]}" % latex.escape(VARIANTS[0]), tex)
        self.assertIn(r"{pilot\textsuperscript{a}}", tex)
        svg = figures.figure_svg(f1).decode("utf-8")
        self.assertIn(">pilot [a]<", svg)
        self.assertIn(">FINAL[%s]<" % VARIANTS[2], svg)
        self.assertIn(METHODOLOGY["reporting"]["pilot_label"], f1["footnotes"][0]["text"])

    def test_f2_data_driven_range_and_error_bars(self):
        f2 = self.figures["F2_heldout_over_iterations"]
        values = [r["value_pct"] for r in f2["data_rows"]] + [r["ci_low_pct"] for r in f2["data_rows"]]
        self.assertEqual(f2["axes"]["y_min"], figures.truncated_floor(values))
        self.assertEqual(figures.truncated_floor([88.9, 98.0, 86.7]), 80.0)
        self.assertEqual(figures.truncated_floor([1.0, 50.0]), 0.0)
        tex = figures.figure_pgfplots(f2).decode("utf-8")
        self.assertEqual(tex.count("error bars/.cd"), len(f2["axes"]["series"]))   # one whisker plot per series

        def high(e):                     # every composite Q06 / E02 rate near 100 %: the axis is truncated
            e["numerator"] = e["denominator"] - 2
            e["value"] = float(e["numerator"]) / e["denominator"]
            e["ci_low"], e["ci_high"] = e["value"] - 0.05, e["value"] + 0.01
        estimates = copy.deepcopy(self.estimates)
        for e in estimates:
            if e["metric_id"] in ("Q06", "E02") and e["block"] == "composite" and \
                    e["population"] in ("BASE", "STEP", "FINAL") and set(e["strata"]) <= {"variant", "step"}:
                high(e)
        truncated = self.built(estimates)["F2_heldout_over_iterations"]
        self.assertGreater(truncated["axes"]["y_min"], 0)
        self.assertTrue(any(n.startswith("y axis truncated: it starts at %s%%" % figures._fmt_pct(
            truncated["axes"]["y_min"])) for n in truncated["notes"]))
        self.assertIn("ymin=%s" % figures._c(truncated["axes"]["y_min"]),
                      figures.figure_pgfplots(truncated).decode("utf-8"))
        self.assertIn("axis truncated", figures.figure_svg(truncated).decode("utf-8"))
        self.assertIn("y axis truncated", figures.figure_caption_tex(truncated).decode("utf-8"))

    def test_f3_colorbar_and_bold_cells(self):
        f3 = self.figures["F3_heatmap_model_variant"]
        tex = figures.figure_pgfplots(f3).decode("utf-8")
        for option in ("colormap={saDiverging}{rgb255=(227,73,72) rgb255=(240,239,236) rgb255=(42,120,214)}",
                       "colorbar", "point meta min=%s" % figures._c(-f3["axes"]["v_max"])):
            self.assertIn(option, tex)
        bold = [r for r in f3["data_rows"] if r["ci_excludes_zero"]]
        self.assertEqual([r["ci_excludes_zero"] for r in f3["data_rows"]],
                         [r["ci_low_pp"] > 0 or r["ci_high_pp"] < 0 for r in f3["data_rows"]])
        self.assertEqual(tex.count(r"\textbf{"), len(bold))
        self.assertEqual(figures.figure_svg(f3).decode("utf-8").count('font-weight="700"'), len(bold))
        self.assertTrue(any("descriptive" in n and "bold" in n for n in f3["notes"]))

    def test_f4_generated_is_labelled_diagnostic(self):
        f4 = self.figures["F4_tool_states"]
        self.assertIn("diagnostic", f4["title"])
        self.assertIn("diagnostic", f4["axes"]["y_label"])
        self.assertIn("diagnostic", f4["population"])
        self.assertIn("diagnostic", figures.figure_pgfplots(f4).decode("utf-8").split(r"\begin{axis}")[1])

    def test_f5_log_axis_and_model_labels(self):
        f5 = self.figures["F5_gain_vs_effort"]
        self.assertTrue(f5["axes"]["x_log"])
        tex = figures.figure_pgfplots(f5).decode("utf-8")
        self.assertIn("xmode=log", tex)
        self.assertIn("nodes near coords", tex)
        self.assertIn("[1]", tex)
        self.assertTrue(any(n.startswith("Point labels (model): 1 = %s; 2 = %s" % MODELS) for n in f5["notes"]))
        self.assertEqual(sorted(set(r["label"] for r in f5["data_rows"])), [1, 2])
        zero = copy.deepcopy(self.estimates)
        [e for e in zero if e["metric_id"] == "C02" and e["block"] == "composite" and
         e["strata"] == {"variant": VARIANTS[0], "model_id": MODELS[0], "quantity": "output_tokens"}][0]["numerator"] = 0
        linear = self.built(zero)["F5_gain_vs_effort"]
        self.assertFalse(linear["axes"]["x_log"])
        self.assertNotIn("xmode=log", figures.figure_pgfplots(linear).decode("utf-8"))
        self.assertTrue(any("x axis linear" in n for n in linear["notes"]))
        ET.fromstring(figures.figure_svg(linear))
        self.assertEqual(figures.log_ticks(0.03, 0.4)[0], (0.01, 1.0))

    def test_svg_caption_is_wrapped_never_truncated(self):
        for fid, fig in self.figures.items():
            with self.subTest(figure=fid):
                root = ET.fromstring(figures.figure_svg(fig))
                texts = [t.text or "" for t in root.iter(SVG_NS + "text")]
                self.assertFalse(any(t.endswith("...") for t in texts))
                joined = " ".join(" ".join(texts).split())
                for paragraph in figures.caption_paragraphs(fig):
                    self.assertIn(" ".join(paragraph.split()), joined, fid)
                height = int(root.get("viewBox").split()[3])
                ys = [float(t.get("y")) for t in root.iter(SVG_NS + "text")]
                self.assertLessEqual(max(ys), height)              # the picture grows with its caption

    def test_caption_files(self):
        for fid, fig in self.figures.items():
            with self.subTest(figure=fid):
                tex = figures.figure_caption_tex(fig).decode("utf-8")
                lines = tex.splitlines()
                self.assertTrue(lines[0].startswith("%% Caption of figure %s" % fid))
                self.assertTrue(lines[1].startswith(r"\caption[%s]{%s." % (latex.escape(fig["title"]),
                                                                           latex.escape(fig["title"]))))
                self.assertTrue(lines[1].endswith(r"}\label{fig:study_analysis_001:%s}" % fid))
                self.assertIn(latex.escape("Population: %s" % fig["population"]), tex)
                self.assertEqual(tex_problems(tex), [])
                for note in fig["notes"]:
                    self.assertIn(latex.escape(note.rstrip(".")), tex)
        f1 = figures.figure_caption_tex(self.figures["F1_correctness_before_after"]).decode("utf-8")
        self.assertIn(r"\textsuperscript{a}~" + latex.escape("pilot: " + METHODOLOGY["reporting"]["pilot_label"]),
                      f1)
        self.assertIn("diagnostic", figures.figure_caption_tex(self.figures["F4_tool_states"]).decode("utf-8"))

    def test_addendum_notes_on_figures(self):
        notes = OrderedDict((n["id"], n["text"]) for n in ADDENDUM["table_notes"])

        def carrying(text):
            return set(fid for fid, f in self.figures.items() if any(text in n for n in f["notes"]))
        self.assertEqual(carrying(notes["BL01"]), {"F1_correctness_before_after", "F2_heldout_over_iterations",
                                                   "F3_heatmap_model_variant", "F5_gain_vs_effort"})
        self.assertEqual(carrying(notes["REASONING"]), {"F3_heatmap_model_variant", "F5_gain_vs_effort"})
        self.assertEqual(carrying(notes["EFFECTIVE_STATES"]), {"F4_tool_states"})
        self.assertEqual(carrying(notes["DEGENERATE_CI"]), set())

    def test_degenerate_interval_is_flagged(self):
        estimates = copy.deepcopy(self.estimates)
        target = [e for e in estimates if e["metric_id"] == "Q06" and e["population"] == "BASE"
                  and e["block"] == "composite" and not e["strata"]][0]
        degenerate(target)
        f1 = self.built(estimates)["F1_correctness_before_after"]
        row = [r for r in f1["data_rows"] if r["block"] == "composite" and r["series"] == "BASE"][0]
        self.assertTrue(row["ci_degenerate"])
        note = [n for n in f1["notes"] if n.startswith(DAGGER)]
        self.assertEqual(len(note), 1)
        self.assertIn(OrderedDict((n["id"], n["text"]) for n in ADDENDUM["table_notes"])["DEGENERATE_CI"], note[0])
        self.assertIn("1 interval(s)", note[0])
        self.assertIn("composite, BASE: %.1f%%" % row["value_pct"], figures.figure_svg(f1).decode("utf-8"))
        self.assertIn("]%s" % DAGGER, figures.figure_svg(f1).decode("utf-8"))
        self.assertIn(r"\dag{} " + latex.escape(OrderedDict((n["id"], n["text"]) for n in ADDENDUM["table_notes"])
                                                 ["DEGENERATE_CI"]),
                      figures.figure_caption_tex(f1).decode("utf-8"))
        csv_rows = list(csv.reader(io.StringIO(figures.figure_csv(f1).decode("utf-8"))))
        flagged = [r for r in csv_rows[1:] if r[csv_rows[0].index("ci_degenerate")] == "1"]
        self.assertEqual(len(flagged), 1)

    def test_contract_keys_are_required(self):
        broken = copy.deepcopy(self.estimates)
        del broken[0]["ci_degenerate"]
        with self.assertRaisesRegex(core.AnalysisRefused, "lacks \\['ci_degenerate'\\]"):
            figures.build_figures(broken, METHODOLOGY)
        with self.assertRaisesRegex(core.AnalysisRefused, "foreign metric id"):
            figures.build_figures(self.estimates + [dict(copy.deepcopy(self.estimates[0]), metric_id="X42")],
                                  METHODOLOGY)


class FiguresReviewRound3Test(unittest.TestCase):
    """Regression tests of the verified review findings of fix round 2: IC6
    on every static_feedback figure, a degenerate interval is never bold and
    carries a visible dagger in every rendering."""

    @classmethod
    def setUpClass(cls):
        cls.estimates = synthetic_estimates(synthetic_dataset())
        cls.figures = by_id(figures.build_figures(cls.estimates, METHODOLOGY))

    def pick(self, estimates, metric, population, block, strata):
        hits = [e for e in estimates if e["metric_id"] == metric and e["population"] == population
                and e["block"] == block and dict(e["strata"]) == strata]
        self.assertEqual(len(hits), 1)
        return hits[0]

    def test_ic6_on_every_static_feedback_figure(self):
        ic6 = OrderedDict((c["id"], c["text"]) for c in ADDENDUM["interpretive_caveats"])["IC6"]
        carrying = set(fid for fid, f in self.figures.items() if "IC6: " + ic6 in f["notes"])
        self.assertEqual(carrying, {"F1_correctness_before_after", "F2_heldout_over_iterations",
                                    "F3_heatmap_model_variant", "F5_gain_vs_effort"})
        for fid in carrying:
            self.assertIn(latex.escape("IC6: " + ic6.rstrip(".")),
                          figures.figure_caption_tex(self.figures[fid]).decode("utf-8"))

    def test_degenerate_cell_is_never_bold(self):
        estimates = copy.deepcopy(self.estimates)
        est = self.pick(estimates, "R04", "FINAL", "composite",
                        {"endpoint": "Q06", "variant": VARIANTS[0], "model_id": MODELS[0]})
        est["numerator"] = 3
        est["value"] = 3.0 / est["denominator"]
        degenerate(est)                                  # [6.25, 6.25]: zero width, but away from 0
        f3 = by_id(figures.build_figures(estimates, METHODOLOGY))["F3_heatmap_model_variant"]
        row = [r for r in f3["data_rows"] if r["model"] == MODELS[0] and r["variant"] == VARIANTS[0]][0]
        self.assertTrue(row["ci_degenerate"])
        self.assertGreater(row["ci_low_pp"], 0)
        self.assertIs(row["ci_excludes_zero"], False)
        text = latex.tex_number(figures._gain_text(row["gain_pp"]))
        tex = figures.figure_pgfplots(f3).decode("utf-8")
        self.assertIn("{%s%s}" % (text, latex.DAG), tex)
        self.assertNotIn(r"\textbf{%s}" % text, tex)
        svg = figures.figure_svg(f3).decode("utf-8")
        shown = re.search(r"<text [^>]*>%s%s</text>" % (re.escape(figures._minus(figures._gain_text(row["gain_pp"]))),
                                                        DAGGER), svg)
        self.assertIsNotNone(shown)
        self.assertNotIn("font-weight", shown.group(0))
        self.assertTrue(any("never bold" in n for n in f3["notes"]))

    def test_degenerate_points_carry_a_visible_dagger(self):
        for fid, fig in self.figures.items():             # nothing degenerate in the fixture: no mark, no option
            tex = figures.figure_pgfplots(fig).decode("utf-8")
            self.assertNotIn(r"\dag", tex, fid)
            self.assertNotIn("clip mode", tex, fid)
        estimates = copy.deepcopy(self.estimates)
        final = self.pick(estimates, "Q06", "FINAL", "pilot", {"variant": VARIANTS[0]})
        degenerate(final)
        step = self.pick(estimates, "E02", "STEP", "composite", {"variant": VARIANTS[2], "step": 1})
        degenerate(step)
        drawn = by_id(figures.build_figures(estimates, METHODOLOGY))
        f1, f2 = drawn["F1_correctness_before_after"], drawn["F2_heldout_over_iterations"]
        tex1 = figures.figure_pgfplots(f1).decode("utf-8")
        shift = (1 - len(VARIANTS) / 2.0) * (figures.BAR_WIDTH + figures.BAR_GAP)     # series 1 = FINAL[v0]
        self.assertIn(r"\node[font=\scriptsize, anchor=south, inner sep=1pt, xshift=%spt] at (axis cs:0,%s) {%s};"
                      % (figures._c(shift), figures._c(final["value"] * 100), latex.DAG), tex1)
        tex2 = figures.figure_pgfplots(f2).decode("utf-8")
        dodge = [s["dodge"] for s in f2["axes"]["series"] if s["endpoint"] == "E02" and s["variant"] == VARIANTS[2]][0]
        self.assertIn(r"at (axis cs:%s,%s) {%s};" % (figures._c(1 + dodge), figures._c(step["value"] * 100),
                                                    latex.DAG), tex2)
        for fig, tex in ((f1, tex1), (f2, tex2)):
            self.assertEqual(tex.count(latex.DAG), 1)
            self.assertIn("clip mode=individual", tex)      # a dagger above a 100 % point is not clipped
            self.assertEqual(tex_problems(tex), [])
            svg = figures.figure_svg(fig).decode("utf-8")
            ET.fromstring(svg)
            self.assertEqual(svg.count(">%s</text>" % DAGGER), 1)
            # the CI note's 'marked' names a mark the rendering carries
            self.assertTrue(any("1 interval(s) of zero width marked %s" % DAGGER in n for n in fig["notes"]))


if __name__ == "__main__":
    unittest.main()
