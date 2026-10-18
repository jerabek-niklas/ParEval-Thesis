"""Study figures F1..F5 from the metric estimates: CSV data, self-contained
pgfplots code, a caption file and standalone SVG - renderings of ONE data
table, so a figure in the thesis can always be traced to its numbers.

Figure = OrderedDict(id, title, kind, data_columns, data_rows, axes, notes,
population, unit, block, footnotes). data_rows hold the unrounded estimate
facts (percent = value * 100); rounding happens only in the renderers (CSV 6
decimals, coordinates 3 decimals). figure_caption_tex(fig) gives
\\caption[title]{title, population, unit, block, CI method and every note -
pilot label, diagnostic label, BL01 / REASONING / caveat notes}
\\label{fig:study_analysis_001:<id>} (run.py writes figures/<id>.caption.tex);
the SVG prints the same caption text, wrapped, below the plot (never cut).

pgfplots: one tikzpicture/axis, inline `coordinates`, no external file, no
pgfplots library; colors are defined inside the picture with \\definecolor
(xcolor ships with TikZ). Header comment: \\usepackage{pgfplots} and
\\pgfplotsset{compat=1.18}. SVG: stdlib string building, viewBox, 10-15 px
sans-serif text, legend, a <title> tooltip on every mark.

Colors follow the reference palette of the dataviz method (light surface):
variants take the first three categorical slots in methodology order (they
validate all-pairs, so they are safe in the scatter), BASE a recessive gray,
tool states the palette's validated categorical order (checked with the
method's validator: adjacent CVD and normal-vision separation pass) with the
two inapplicable states in recessive grays, the heatmap a blue (gain) <->
red (loss) diverging ramp with a gray midpoint (pgfplots: the same three
stops as the colorbar's colormap). Low-contrast hues are relieved by the
legend, the <title> tooltips and the data CSV.

Readings (documented deviations): F2-F5 show the composite block (F1 shows
every block). F1: legend FINAL[<variant>], the pilot tick carries the pilot
footnote mark. F2: one axis with a data-driven y range (lower bound
floor((min - 2) / 5) * 5 over the plotted values and CI bounds, at least 0,
upper 100; the caption states the truncation) and CI error bars; the series
are dodged horizontally by DODGE steps so that whiskers do not overlap (the
data CSV keeps the integer steps). F3 paints the cells explicitly (\\fill
per cell, n/a cells gray) instead of a matrix plot so missing cells can never
take a colormap value; its colorbar uses the same diverging stops, and a
value is bold when its 95% CI excludes 0 and is not degenerate (descriptive,
not a test). F4: the
GENERATED population is labelled diagnostic in the title and axis. F5: log x
axis (when every token count is positive; otherwise linear, stated in the
notes) and point labels 1..n by model with the key in the caption.

Fail closed as tables.py: row sets never come from whichever estimates exist
(tools: the frozen core lists; models: the dataset summary when given, and
always the per-model Q01 BASE estimates must partition all base cells and
R04 must carry the same models for every variant), BASE / STEP / FINAL bars
and lines must rest on the identical cohort (tables.same_cohort), the
estimates must satisfy the contract keys (tables.EstimateIndex), and the
CI statement of a figure is generated from the intervals it carries
(tables.interval_audit: methodology replicate counts, or the producer's
EXPLORATORY label, which then reaches the title and notes; a zero-width
interval is flagged in the data, the tooltip and the DEGENERATE_CI note, and
carries a visible dagger at its point - pgfplots \\node (clip mode=individual,
so it is not clipped at 100 %), SVG text; F3: after the cell value, and such
a cell is never bold, a zero-width interval being no evidence of certainty).
An explicitly passed addendum is checked like core.load_addendum
(tables.checked_addendum).
The data rows carry the replicate count and the exclusion count of every
estimate. F1's and F2's pgfplots draw the bars / lines without error bars
and the whiskers in separate invisible plots (same explicit bar shift /
dodge) holding only the points whose interval exists, so a point without a
CI never gets a zero-length whisker.
"""
from __future__ import annotations

import csv
import io
import math
import textwrap
from collections import OrderedDict
from xml.sax.saxutils import escape as xml_escape

from thesis.study_analysis import core
from thesis.study_analysis.latex import escape as tex_escape, mark as tex_mark, tex_number
from thesis.study_analysis.tables import (C02_OUTPUT, C02_TOKEN_KEY, DAGGER, ENDPOINTS, EXPLORATORY, PILOT_BLOCK,
                                          PILOT_MARK, TABLE_IDS, Disclosure, EstimateIndex, _merged, cell,
                                          checked_addendum, ci_note_text, distribution, frozen_tools,
                                          interval_audit, is_exploratory, ordered, refuse, same_cohort, source_of,
                                          summarize_dataset)

FIGURE_IDS = ("F1_correctness_before_after", "F2_heldout_over_iterations", "F3_heatmap_model_variant",
              "F4_tool_states", "F5_gain_vs_effort")
FIGURE_KEYS = ("id", "title", "kind", "data_columns", "data_rows", "axes", "notes", "population", "unit", "block",
               "footnotes")
VARIANT_COLORS = ("#2a78d6", "#eb6834", "#1baf7a")          # categorical slots 1-3 (blue, orange, aqua)
VARIANT_MARKS = (("circle", "*"), ("square", "square*"), ("triangle", "triangle*"))
BASE_COLOR = "#8a8984"
# analysis states: the palette's validated categorical order (adjacent CVD dE >= 9.1, normal >= 19.6);
# the two inapplicable states are deliberately achromatic grays (recessive, never a category of their own)
STATE_COLORS = OrderedDict([("COMPLETED", "#2a78d6"), ("PARTIAL", "#eb6834"), ("TIMEOUT", "#1baf7a"),
                            ("TOOL_ERROR", "#eda100"), ("NOT_ANALYZED", "#e87ba4"),
                            ("NOT_APPLICABLE", "#d2d1cc"), ("ABSENT_INAPPLICABLE", "#8c8b85")])
LOSS, MIDPOINT, GAIN, MISSING = "#e34948", "#f0efec", "#2a78d6", "#d9d8d4"
TEXT, TEXT2, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#8a8984", "#ffffff"
FONT = "Helvetica, Arial, sans-serif"
WIDTH, HEIGHT = 760, 440                    # SVG width; HEIGHT = plot area height (the caption block follows)
BAR_WIDTH, BAR_GAP = 7.0, 2.0               # F1 pgfplots bar width and gap (pt): explicit bar shifts
DODGE = 0.04                                # F2 horizontal offset between series (in steps)
WRAP = 125                                  # SVG caption characters per line (10 px text over ~720 px)
DIAGNOSTIC = "diagnostic"


def _pct(value):
    return None if value is None else float(value) * 100.0


def _row(est, labels):
    row = OrderedDict(labels)
    row["numerator"], row["denominator"] = est["numerator"], est["denominator"]
    row["value_pct"], row["ci_low_pct"], row["ci_high_pct"] = (_pct(est["value"]), _pct(est["ci_low"]),
                                                               _pct(est["ci_high"]))
    row["replicates"], row["excluded"] = est["replicates"], cell(est)["excluded"]
    row["ci_degenerate"] = est["ci_degenerate"]
    return row


class _FCtx:
    def __init__(self, ix, methodology, addendum, disclosure, summary):
        self.ix, self.meth, self.addendum, self.disclosure, self.summary = (ix, methodology, addendum, disclosure,
                                                                            summary)
        self.pilot_text = "pilot: %s; %s" % (methodology["reporting"]["pilot_label"],
                                             methodology["statistics"]["small_cluster_warning"])


def _figure(ctx, fid, title, kind, columns, rows, axes, notes, drawn, population, unit, block, footnotes=(),
            intervals=(), sources=()):
    """`drawn`: the estimates plotted; `intervals`: those whose interval is
    drawn (zero-width ones get the DEGENERATE_CI note); `sources`: further
    estimates the figure uses (disclosures). A producer EXPLORATORY label
    reaches the title and the notes."""
    for row in rows:
        if list(row) != list(columns):
            refuse("%s: data row keys %s do not match %s" % (fid, list(row), columns))
    notes = list(notes)
    if is_exploratory([cell(e) for e in drawn]):
        title = "%s (not confirmatory): %s" % (EXPLORATORY, title)
        notes.append("%s: the estimates carry the producer's %s label (bootstrap replicate counts other than the "
                     "methodology's); not confirmatory" % (EXPLORATORY, EXPLORATORY))
    zero = [e for e in intervals if e["ci_degenerate"]]
    if zero:
        notes.append("%s %s (%d interval(s): %s)" % (
            DAGGER, ctx.disclosure.text("DEGENERATE_CI"), len(zero),
            "; ".join("%s %s {%s}" % (e["population"], e["block"], ", ".join(
                "%s=%s" % (k, v) for k, v in sorted((e["strata"] or {}).items()))) for e in zero)))
    for nid, text in ctx.disclosure.apply(fid, [source_of(e) for e in list(drawn) + list(sources)]):
        notes.append("%s: %s" % (nid, text))
    return OrderedDict([("id", fid), ("title", title), ("kind", kind), ("data_columns", list(columns)),
                        ("data_rows", rows), ("axes", axes), ("notes", notes), ("population", population),
                        ("unit", unit), ("block", block),
                        ("footnotes", [OrderedDict([("mark", m), ("text", t)]) for m, t in footnotes])])


def _interval_note(methodology, estimates, fid, prefix):
    """The CI statement of the intervals a figure carries (replicate counts
    as the estimates state them, checked against the methodology)."""
    return prefix + ci_note_text(methodology, interval_audit([cell(e) for e in estimates], methodology, fid))


def figure_models(ix, meth, summary=None):
    """The composite models of F3/F5: the dataset's models when a summary is
    given; in any case the per-model Q01 BASE estimates must partition all
    base cells (a model missing from the producer output refuses) and R04 Q06
    must carry exactly these models for every variant."""
    block = core.COMPOSITE
    found = ix.values("Q01", block, "model_id", None, "BASE")
    if summary is not None:
        models = list(summary["blocks"][block]["model_ids"])
        if set(models) != found:
            refuse("figures: Q01 BASE models %s, the dataset has %s" % (sorted(found), models))
    else:
        models = ordered(found, core.MODELS)
    if not models:
        refuse("figures: no per-model estimates")
    total = ix.get("Q01", block, {}, "BASE")["denominator"]
    parts = sum(ix.get("Q01", block, {"model_id": m}, "BASE")["denominator"] for m in models)
    if parts != total:
        refuse("figures: the per-model Q01 BASE estimates cover %s of %s base cells (a model is missing)" % (
            parts, total))
    for v in meth["strata"]["variant"]:
        got = ix.values("R04", block, "model_id", {"endpoint": "Q06", "variant": v})
        if got != set(models):
            refuse("figures: R04 Q06 %s covers models %s, expected %s" % (v, sorted(got), models))
    return models


def nice_ticks(lo, hi, target=5):
    """Deterministic 1/2/2.5/5 x 10^k ticks covering [lo, hi]."""
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo < 1e-9:
        lo, hi = lo - 1.0, hi + 1.0
    raw = (hi - lo) / float(target)
    base = 10.0 ** math.floor(math.log10(raw))
    step = base
    for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = multiple * base
        if step >= raw - 1e-12:
            break
    start = math.floor(lo / step + 1e-9) * step
    end = math.ceil(hi / step - 1e-9) * step
    count = int(round((end - start) / step))
    return [start + i * step for i in range(count + 1)], step


def log_ticks(lo, hi):
    """(decade bounds, ticks at 1/2/5 x 10^k) covering [lo, hi] > 0."""
    if lo <= 0 or hi <= 0:
        refuse("log ticks need positive bounds (%r, %r)" % (lo, hi))
    a, b = math.floor(math.log10(lo) + 1e-12), math.ceil(math.log10(hi) - 1e-12)
    if b <= a:
        b = a + 1
    ticks = [m * 10.0 ** k for k in range(a, b + 1) for m in (1.0, 2.0, 5.0) if m * 10.0 ** k <= 10.0 ** b + 1e-12]
    return (10.0 ** a, 10.0 ** b), ticks


def _decimals(step):
    for digits in (0, 1, 2, 3):
        if abs(step * 10 ** digits - round(step * 10 ** digits)) < 1e-9:
            return digits
    return 4


def _span(values, include_zero=True):
    values = [v for v in values if v is not None]
    if include_zero:
        values.append(0.0)
    return (min(values), max(values)) if values else (0.0, 1.0)


def truncated_floor(values):
    """F2 lower bound: floor((min - 2) / 5) * 5, at least 0."""
    values = [v for v in values if v is not None]
    if not values:
        return 0.0
    return max(0.0, math.floor((min(values) - 2.0) / 5.0) * 5.0)


def _fmt_pct(value):
    return ("%.1f" % value).rstrip("0").rstrip(".") if value is not None else "--"


# -- builders ------------------------------------------------------------------------------------------------

def _f1(ctx):
    ix, meth = ctx.ix, ctx.meth
    blocks = list(meth["strata"]["block"])
    variants = list(meth["strata"]["variant"])
    rows, drawn = [], []
    for block in blocks:
        base = ix.get("Q06", block, {}, "BASE")
        drawn.append(base)
        rows.append(_row(base, [("block", block), ("series", "BASE"), ("population", "BASE")]))
        for v in variants:
            final = ix.get("Q06", block, {"variant": v}, "FINAL")
            same_cohort(cell(base), cell(final), "F1: Q06 FINAL[%s] vs BASE (%s)" % (v, block))
            drawn.append(final)
            rows.append(_row(final, [("block", block), ("series", v), ("population", "FINAL")]))
    axes = OrderedDict([("x_label", "Block"), ("y_label", "Q06 correctness pass (%)"), ("y_min", 0.0),
                        ("y_max", 100.0), ("groups", blocks),
                        ("group_marks", OrderedDict((b, PILOT_MARK) for b in blocks if b == PILOT_BLOCK)),
                        ("series", ["BASE"] + variants),
                        ("legend", ["BASE"] + ["FINAL[%s]" % v for v in variants]),
                        ("colors", [BASE_COLOR] + list(VARIANT_COLORS[:len(variants)]))])
    notes = ["Q06 correctness pass on BASE vs FINAL[v] (identical base-cell cohort, checked) per block",
             _interval_note(meth, drawn, "F1", "error bars: ")]
    footnotes = [(PILOT_MARK, ctx.pilot_text)] if PILOT_BLOCK in blocks else []
    columns = ["block", "series", "population", "numerator", "denominator", "value_pct", "ci_low_pct", "ci_high_pct",
               "replicates", "excluded", "ci_degenerate"]
    return _figure(ctx, "F1_correctness_before_after", "Correctness before and after repair (Q06, BASE vs FINAL)",
                   "grouped_bar", columns, rows, axes, notes, drawn, "BASE and FINAL[v] (identical base-cell "
                   "cohort)", "base cell", ", ".join(blocks), footnotes, intervals=drawn)


def _f2(ctx):
    ix, meth = ctx.ix, ctx.meth
    variants = list(meth["strata"]["variant"])
    steps = [str(s) for s in meth["strata"]["iteration"]]
    block = core.COMPOSITE
    rows, series, drawn = [], [], []
    n_series = len(ENDPOINTS) * len(variants)
    for e_index, endpoint in enumerate(ENDPOINTS):
        base = ix.get(endpoint, block, {}, "BASE")
        for v_index, v in enumerate(variants):
            final = ix.get(endpoint, block, {"variant": v}, "FINAL")
            for k in steps:
                est = ix.get(endpoint, block, {"variant": v, "step": k}, "STEP")
                same_cohort(cell(base), cell(est), "F2: %s STEP[%s][%s] vs BASE" % (endpoint, v, k))
                for ref, which in ((base, steps[0]), (final, steps[-1])):
                    if k == which and (est["numerator"], est["denominator"]) != (ref["numerator"], ref["denominator"]):
                        refuse("F2: %s STEP[%s][%s] contradicts %s" % (endpoint, v, k, ref["population"]))
                drawn.append(est)
                rows.append(_row(est, [("endpoint", endpoint), ("variant", v), ("step", int(k))]))
            index = e_index * len(variants) + v_index
            series.append(OrderedDict([("endpoint", endpoint), ("variant", v), ("label", "%s %s" % (endpoint, v)),
                                       ("color", VARIANT_COLORS[v_index]), ("dashed", e_index == 1),
                                       ("mark", VARIANT_MARKS[e_index][0]),
                                       ("dodge", (index - (n_series - 1) / 2.0) * DODGE)]))
    lower = truncated_floor([r["value_pct"] for r in rows] + [r["ci_low_pct"] for r in rows])
    axes = OrderedDict([("x_label", "Repair step k (STEP[v][k]; last artifact carried forward)"),
                        ("y_label", "Rate (%)"), ("y_min", lower), ("y_max", 100.0), ("truncated", lower > 0),
                        ("x_values", [int(k) for k in steps]),
                        ("series", series)])
    notes = ["Composite block; Q06 correctness pass (solid) and E02 enhanced all-pass (dashed) on the identical "
             "base-cell cohort per step (G02 overfitting check); STEP[v][0] == BASE and STEP[v][%s] == FINAL[v] "
             "(checked)" % steps[-1]]
    if lower > 0:
        notes.append("y axis truncated: it starts at %s%%, not at 0 (data-driven lower bound floor((min - 2) / 5) "
                     "* 5 over the plotted values and CI bounds); the series are dodged horizontally by %s steps so "
                     "that the error bars do not overlap" % (_fmt_pct(lower), DODGE))
    else:
        notes.append("y axis from 0 to 100%%; the series are dodged horizontally by %s steps so that the error "
                     "bars do not overlap" % DODGE)
    notes.append(_interval_note(meth, drawn, "F2", "error bars: "))
    columns = ["endpoint", "variant", "step", "numerator", "denominator", "value_pct", "ci_low_pct", "ci_high_pct",
               "replicates", "excluded", "ci_degenerate"]
    return _figure(ctx, "F2_heldout_over_iterations", "ParEval vs held-out pass rate over repair steps", "line",
                   columns, rows, axes, notes, drawn, "STEP[v][k], k = %s (identical base-cell cohort)" %
                   ", ".join(steps), "base cell", block, intervals=drawn)


def _f3(ctx):
    ix, meth = ctx.ix, ctx.meth
    variants = list(meth["strata"]["variant"])
    block = core.COMPOSITE
    models = figure_models(ix, meth, ctx.summary)
    rows, drawn = [], []
    for m in models:
        for v in variants:
            est = ix.get("R04", block, {"endpoint": "Q06", "variant": v, "model_id": m})
            drawn.append(est)
            low, high = _pct(est["ci_low"]), _pct(est["ci_high"])
            # a degenerate (zero-width) interval is no evidence of certainty (addendum ci_degenerate): never bold
            excludes = None if low is None or high is None else (
                (low > 0 or high < 0) and not est["ci_degenerate"])
            rows.append(OrderedDict([("model", m), ("variant", v), ("numerator", est["numerator"]),
                                     ("denominator", est["denominator"]), ("gain_pp", _pct(est["value"])),
                                     ("ci_low_pp", low), ("ci_high_pp", high), ("ci_excludes_zero", excludes),
                                     ("replicates", est["replicates"]), ("excluded", cell(est)["excluded"]),
                                     ("ci_degenerate", est["ci_degenerate"])]))
    lo, hi = _span([r["gain_pp"] for r in rows])
    ticks, _step = nice_ticks(-max(abs(lo), abs(hi)), max(abs(lo), abs(hi)))
    axes = OrderedDict([("x_label", "Variant"), ("y_label", "Model"), ("columns", variants), ("rows", models),
                        ("v_max", max(abs(ticks[0]), abs(ticks[-1]))), ("value_label", "R04 Q06 net gain (pp)")])
    notes = ["Composite block; cell = R04 net gain of Q06 correctness pass (FINAL[v] - BASE) in percentage points; "
             "blue = gain, red = loss, gray midpoint = 0 (colour scale beside the plot); bold value = its 95%% CI "
             "excludes 0 (a degenerate zero-width interval is never bold; its value carries %s); descriptive per "
             "model (unadjusted CIs, no test, no ranking)" % DAGGER,
             _interval_note(meth, drawn, "F3", "CIs (in the data CSV): ")]
    return _figure(ctx, "F3_heatmap_model_variant", "Net correctness gain per model and variant (R04, Q06)", "heatmap",
                   ["model", "variant", "numerator", "denominator", "gain_pp", "ci_low_pp", "ci_high_pp",
                    "ci_excludes_zero", "replicates", "excluded", "ci_degenerate"], rows, axes, notes, drawn,
                   "BASE paired with FINAL[v] (identical base-cell cohort per model)", "base cell", block,
                   intervals=drawn)


def _f4(ctx):
    ix, meth = ctx.ix, ctx.meth
    block = core.COMPOSITE
    states = list(meth["state_vocabularies"]["tool_states"])
    rows, tools, drawn = [], [], []
    for stage, metric in (("static", "S01"), ("dynamic", "D01")):
        coverage = "S02" if metric == "S01" else "D02"
        for tool in frozen_tools(ix, stage, [block], coverage, ("GENERATED",)):
            dist = distribution(ix, metric, block, {"tool": tool}, "state", states, "GENERATED")
            tools.append(tool)
            for s in states:
                c = dist[s]
                if c["source"] is not None:
                    drawn.append(ix.get(metric, block, {"tool": tool, "state": s}, "GENERATED"))
                rows.append(OrderedDict([("stage", stage), ("tool", tool), ("state", s), ("numerator", c["numerator"]),
                                         ("denominator", c["denominator"]), ("share_pct", _pct(c["value"]))]))
    if not tools:
        refuse("F4: no tool coverage estimates")
    shown = [s for s in states if any(r["numerator"] for r in rows if r["state"] == s)]
    axes = OrderedDict([("x_label", "Tool"), ("y_label", "Share of GENERATED artifacts (%%, %s)" % DIAGNOSTIC),
                        ("y_min", 0.0), ("y_max", 100.0), ("categories", tools), ("states", shown),
                        ("colors", [STATE_COLORS.get(s, BASE_COLOR) for s in shown])])
    notes = ["Composite block, GENERATED (%s); S01 (static) / D01 (dynamic) analysis state per tool; COMPLETED "
             "does not imply defect-free code; inapplicable states are not analysis gaps"
             % meth["populations"]["GENERATED"]["use"]]
    return _figure(ctx, "F4_tool_states", "Analysis tool states (S01/D01, GENERATED - %s)" % DIAGNOSTIC,
                   "stacked_bar", ["stage", "tool", "state", "numerator", "denominator", "share_pct"], rows, axes,
                   notes, drawn, "GENERATED (%s)" % meth["populations"]["GENERATED"]["use"], "artifact x tool", block)


def output_tokens(ix, block, strata):
    found = [e for e in (ix.get("C02", block, _merged(strata, **{C02_TOKEN_KEY: value}), "REPAIR_CANDIDATES",
                                required=False) for value in C02_OUTPUT) if e is not None]
    if len(found) != 1:
        refuse("C02 output tokens for %s %s: %d estimates (strata %s in %s expected once)" % (
            block, dict(strata), len(found), C02_TOKEN_KEY, list(C02_OUTPUT)))
    return found[0]


def _f5(ctx):
    ix, meth = ctx.ix, ctx.meth
    variants = list(meth["strata"]["variant"])
    block = core.COMPOSITE
    models = figure_models(ix, meth, ctx.summary)
    rows, drawn, tokens_used = [], [], []
    for v in variants:
        for index, m in enumerate(models):
            gain = ix.get("R04", block, {"endpoint": "Q06", "variant": v, "model_id": m})
            drawn.append(gain)
            token_est = output_tokens(ix, block, OrderedDict([("variant", v), ("model_id", m)]))
            tokens_used.append(token_est)
            tokens = token_est["numerator"]
            rows.append(OrderedDict([("model", m), ("label", index + 1), ("variant", v), ("output_tokens", tokens),
                                     ("output_tokens_millions", float(tokens) / 1e6), ("gain_pp", _pct(gain["value"])),
                                     ("gain_numerator", gain["numerator"]), ("denominator", gain["denominator"])]))
    if not rows:
        refuse("F5: no per-model estimates")
    xs = [r["output_tokens_millions"] for r in rows]
    log_x = min(xs) > 0
    if log_x:
        (x_min, x_max), _ticks = log_ticks(min(xs), max(xs))
    else:
        x_ticks, _ = nice_ticks(0.0, max(xs + [1e-6]))
        x_min, x_max = 0.0, x_ticks[-1]
    y_lo, y_hi = _span([r["gain_pp"] for r in rows])
    y_ticks, _ = nice_ticks(y_lo, y_hi)
    axes = OrderedDict([("x_label", "Repair output tokens (millions, C02%s)" % (", log scale" if log_x else "")),
                        ("y_label", "R04 Q06 net gain (pp)"), ("x_log", log_x),
                        ("x_min", x_min), ("x_max", x_max), ("y_min", y_ticks[0]), ("y_max", y_ticks[-1]),
                        ("series", variants), ("colors", list(VARIANT_COLORS[:len(variants)])),
                        ("marks", [m[0] for m in VARIANT_MARKS[:len(variants)]]),
                        ("labels", OrderedDict((i + 1, m) for i, m in enumerate(models)))])
    notes = ["Composite block; one point per (model, variant): repair output tokens of the variant's repair "
             "candidates vs net gain of Q06 correctness pass; descriptive only (no ranking, no test)",
             "Point labels (model): " + "; ".join("%d = %s" % (i + 1, m) for i, m in enumerate(models))]
    if not log_x:
        notes.append("x axis linear: a token count of 0 cannot be shown on a log scale")
    return _figure(ctx, "F5_gain_vs_effort", "Net correctness gain vs repair output tokens", "scatter",
                   ["model", "label", "variant", "output_tokens", "output_tokens_millions", "gain_pp",
                    "gain_numerator", "denominator"], rows, axes, notes, drawn,
                   "FINAL[v] vs BASE (R04) and REPAIR_CANDIDATES (C02 output tokens, %s)" %
                   meth["populations"]["REPAIR_CANDIDATES"]["use"], "model x variant", block, sources=tokens_used)


def build_figures(estimates, methodology, dataset_summary=None, addendum=None):
    """The study figures in FIGURE_IDS order. `dataset_summary` (optional,
    tables.summarize_dataset or the core.Dataset) pins the model set of F3/F5
    to the dataset; without it the per-model estimates must still partition
    the base cells. `addendum` None -> core.load_addendum(methodology=...), a
    passed one is checked the same way (tables.checked_addendum)."""
    if isinstance(dataset_summary, core.Dataset):
        dataset_summary = summarize_dataset(dataset_summary)
    if dataset_summary is not None and (not isinstance(dataset_summary, dict) or "blocks" not in dataset_summary):
        refuse("build_figures: dataset_summary must be summarize_dataset(dataset)")
    addendum = checked_addendum(addendum, methodology)
    ix = EstimateIndex(list(estimates), methodology, addendum)
    ctx = _FCtx(ix, methodology, addendum, Disclosure(addendum, methodology, TABLE_IDS + FIGURE_IDS),
                dataset_summary)
    figures = [_f1(ctx), _f2(ctx), _f3(ctx), _f4(ctx), _f5(ctx)]
    if tuple(f["id"] for f in figures) != FIGURE_IDS:
        refuse("figure ids drifted")
    return figures


# -- CSV / caption -----------------------------------------------------------------------------------------

def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        text = "%.6f" % value
        return "0.000000" if text == "-0.000000" else text
    return str(value)


def figure_csv(fig):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fig["data_columns"])
    for row in fig["data_rows"]:
        writer.writerow([_csv_value(row[c]) for c in fig["data_columns"]])
    return buffer.getvalue().encode("utf-8")


def caption_paragraphs(fig):
    """The caption text of a figure as plain paragraphs (title, population /
    unit / block, every note, every footnote)."""
    out = ["Population: %s; unit: %s; block: %s." % (fig["population"], fig["unit"], fig["block"])]
    out += [note if note.endswith(".") else note + "." for note in fig["notes"]]
    out += ["[%s] %s." % (f["mark"], f["text"].rstrip(".")) for f in fig["footnotes"]]
    return out


def figure_caption_tex(fig):
    """\\caption[short]{full caption}\\label{fig:study_analysis_001:<id>} (UTF-8 bytes, LF)."""
    parts = [tex_escape(fig["title"]) + "."]
    parts.append(tex_escape("Population: %s; unit: %s; block: %s." % (fig["population"], fig["unit"],
                                                                       fig["block"])))
    parts += [tex_escape(note if note.endswith(".") else note + ".") for note in fig["notes"]]
    parts += ["%s~%s" % (tex_mark(f["mark"]), tex_escape(f["text"].rstrip(".") + ".")) for f in fig["footnotes"]]
    lines = ["%% Caption of figure %s of %s - generated by thesis/study_analysis/figures.py; do not edit by hand."
             % (fig["id"], core.ANALYSIS_ID),
             r"\caption[%s]{%s}\label{fig:%s:%s}" % (tex_escape(fig["title"]), " ".join(parts), core.ANALYSIS_ID,
                                                     fig["id"])]
    return ("\n".join(lines) + "\n").encode("utf-8")


# -- pgfplots ------------------------------------------------------------------------------------------------

def _c(value):
    text = "%.3f" % float(value)
    return "0.000" if text == "-0.000" else text


def _hex(color):
    return color.lstrip("#").upper()


def _labels(values):
    return "{" + ",".join("{%s}" % tex_escape(v) for v in values) + "}"


def _ticks(count):
    return "{" + ",".join(str(i) for i in range(count)) + "}"


def _pgf_document(fig, colors, options, body):
    lines = ["%% Figure %s of %s - generated by thesis/study_analysis/figures.py; do not edit by hand."
             % (fig["id"], core.ANALYSIS_ID),
             r"% Preamble: \usepackage{pgfplots}",
             r"%           \pgfplotsset{compat=1.18}",
             "% " + " ".join(fig["title"].split()),
             "%% Caption: figures/%s.caption.tex (figure_caption_tex)" % fig["id"]]
    lines += ["% " + " ".join(note.split()) for note in fig["notes"]]
    lines.append(r"\begin{tikzpicture}")
    lines += [r"\definecolor{%s}{HTML}{%s}" % (name, _hex(color)) for name, color in colors]
    lines.append(r"\begin{axis}[")
    lines.append(",\n".join("  " + o for o in options + ["title={%s}" % tex_escape(fig["title"]),
                                                         r"title style={font=\small}"]))
    lines.append("]")
    lines += body
    lines += [r"\end{axis}", r"\end{tikzpicture}"]
    return ("\n".join(lines) + "\n").encode("utf-8")


_LEGEND = r"legend style={at={(1.02,1)},anchor=north west,font=\small,draw=none}"


def _whisker(x, row):
    up = max(0.0, row["ci_high_pct"] - row["value_pct"])
    down = max(0.0, row["value_pct"] - row["ci_low_pct"])
    return "(%s,%s) += (0,%s) -= (0,%s)" % (x, _c(row["value_pct"]), _c(up), _c(down))


def _has_ci(row):
    return row["value_pct"] is not None and row["ci_low_pct"] is not None and row["ci_high_pct"] is not None


def _is_degenerate(row):
    return _has_ci(row) and bool(row.get("ci_degenerate"))


def _dagger_node(x, value, xshift=None):
    """pgfplots: the dagger above a point whose interval is degenerate
    (spec 2.1: every rendered degenerate interval carries the mark)."""
    shift = ", xshift=%spt" % _c(xshift) if xshift is not None else ""
    return r"\node[font=\scriptsize, anchor=south, inner sep=1pt%s] at (axis cs:%s,%s) {%s};" % (
        shift, x, _c(value), tex_mark(DAGGER))


# nodes inside the axis are not clipped under clip mode=individual (each \addplot keeps its own clip path), so a
# dagger above a 100 % bar stays visible
_NODE_CLIP = "clip mode=individual"


def _pgf_grouped_bar(fig):
    axes = fig["axes"]
    groups, series = axes["groups"], axes["series"]
    colors = [("saSeries%s" % chr(65 + i), c) for i, c in enumerate(axes["colors"])]
    marks = axes.get("group_marks") or {}
    ticklabels = "{" + ",".join("{%s%s}" % (tex_escape(g), tex_mark(marks[g]) if g in marks else "")
                                for g in groups) + "}"
    options = ["width=9.5cm", "height=7cm", "ybar", "bar width=%spt" % _c(BAR_WIDTH), "enlarge x limits=0.25",
               "ymin=%s" % _c(axes["y_min"]), "ymax=%s" % _c(axes["y_max"]), "xtick=" + _ticks(len(groups)),
               "xticklabels=" + ticklabels, "xlabel={%s}" % tex_escape(axes["x_label"]),
               "ylabel={%s}" % tex_escape(axes["y_label"]), "ymajorgrids", "legend cell align=left", _LEGEND]
    body, daggers = [], []
    for i, name in enumerate(series):
        # explicit bar shift: the automatic one would count the whisker plots as further bar series
        shift = (i - (len(series) - 1) / 2.0) * (BAR_WIDTH + BAR_GAP)
        coords, whiskers = [], []
        for g, group in enumerate(groups):
            row = [r for r in fig["data_rows"] if r["block"] == group and r["series"] == name][0]
            if row["value_pct"] is None:
                continue
            coords.append("(%d,%s)" % (g, _c(row["value_pct"])))
            if _has_ci(row):
                whiskers.append(_whisker(str(g), row))
            if _is_degenerate(row):
                daggers.append(_dagger_node(str(g), row["value_pct"], shift))
        body.append(r"\addplot[draw=white, fill=%s, area legend, bar shift=%spt] coordinates {%s};"
                    % (colors[i][0], _c(shift), " ".join(coords)))
        body.append(r"\addlegendentry{%s}" % tex_escape(axes["legend"][i]))
        if whiskers:                       # only the bars whose interval exists get a whisker
            body.append(r"\addplot[forget plot, draw=none, fill=none, bar shift=%spt, error bars/.cd, y dir=both, "
                        r"y explicit, error bar style={draw=black, line width=0.6pt}] coordinates {%s};"
                        % (_c(shift), " ".join(whiskers)))
    if daggers:
        options.append(_NODE_CLIP)
        body += daggers
    return _pgf_document(fig, colors, options, body)


def _pgf_line(fig):
    axes = fig["axes"]
    colors, body = [], []
    xs = axes["x_values"]
    options = ["width=10.5cm", "height=7cm", "xmin=%s" % _c(xs[0] - 0.25), "xmax=%s" % _c(xs[-1] + 0.25),
               "xtick={%s}" % ",".join(str(x) for x in xs), "ymin=%s" % _c(axes["y_min"]),
               "ymax=%s" % _c(axes["y_max"]), "xlabel={%s}" % tex_escape(axes["x_label"]),
               "ylabel={%s}" % tex_escape(axes["y_label"]), "ymajorgrids", "legend cell align=left", _LEGEND]
    pgf_marks = {"circle": "*", "square": "square*", "triangle": "triangle*"}
    daggers = []
    for i, s in enumerate(axes["series"]):
        name = "saSeries%s" % chr(65 + i)
        colors.append((name, s["color"]))
        pts = [r for r in fig["data_rows"] if r["endpoint"] == s["endpoint"] and r["variant"] == s["variant"]]
        coords = " ".join("(%s,%s)" % (_c(r["step"] + s["dodge"]), _c(r["value_pct"])) for r in pts
                          if r["value_pct"] is not None)
        body.append(r"\addplot[color=%s, thick, mark=%s, %s] coordinates {%s};"
                    % (name, pgf_marks[s["mark"]], "dashed" if s["dashed"] else "solid", coords))
        body.append(r"\addlegendentry{%s}" % tex_escape(s["label"]))
        whiskers = [_whisker(_c(r["step"] + s["dodge"]), r) for r in pts if _has_ci(r)]
        if whiskers:
            body.append(r"\addplot[forget plot, draw=none, mark=none, error bars/.cd, y dir=both, y explicit, "
                        r"error bar style={draw=%s, solid, line width=0.6pt}] coordinates {%s};"
                        % (name, " ".join(whiskers)))
        daggers += [_dagger_node(_c(r["step"] + s["dodge"]), r["value_pct"]) for r in pts if _is_degenerate(r)]
    if daggers:
        options.append(_NODE_CLIP)
        body += daggers
    return _pgf_document(fig, colors, options, body)


def heat_color(value, v_max):
    if value is None:
        return MISSING
    t = 0.0 if v_max <= 0 else min(1.0, abs(value) / float(v_max))
    pole = GAIN if value > 0 else LOSS
    a, b = _rgb(MIDPOINT), _rgb(pole)
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def text_on(color):
    r, g, b = (x / 255.0 for x in _rgb(color))
    return "white" if (0.2126 * r + 0.7152 * g + 0.0722 * b) < 0.45 else "black"


def _gain_text(value):
    return "n/a" if value is None else ("%+.1f" % value if abs(value) >= 0.05 else "0.0")


def _minus(text):
    """SVG display text: a leading hyphen-minus becomes U+2212 MINUS SIGN."""
    return "−" + text[1:] if text.startswith("-") else text


def _c0(text):
    """Tick text without a negative zero ("-0" / "-0.0" -> "0" / "0.0")."""
    return text[1:] if text.startswith("-") and not text.strip("-0.") else text


def _colormap():
    return "colormap={saDiverging}{%s}" % " ".join("rgb255=(%d,%d,%d)" % _rgb(c) for c in (LOSS, MIDPOINT, GAIN))


def _pgf_heatmap(fig):
    axes = fig["axes"]
    cols, rows_ = axes["columns"], axes["rows"]
    colors, body = [], []
    v_max = axes["v_max"]
    options = ["width=%scm" % _c(3.0 + 2.2 * len(cols)), "height=%scm" % _c(2.0 + 0.6 * len(rows_)),
               "xmin=-0.5", "xmax=%s" % _c(len(cols) - 0.5), "ymin=-0.5", "ymax=%s" % _c(len(rows_) - 0.5),
               "y dir=reverse", "axis on top", "tick style={draw=none}", "xtick=" + _ticks(len(cols)),
               "xticklabels=" + _labels(cols), "ytick=" + _ticks(len(rows_)), "yticklabels=" + _labels(rows_),
               "xlabel={%s}" % tex_escape(axes["x_label"]), "ylabel={%s}" % tex_escape(axes["y_label"]),
               r"x tick label style={font=\small}", r"y tick label style={font=\small}", _colormap(), "colorbar",
               "point meta min=%s" % _c(-v_max), "point meta max=%s" % _c(v_max),
               r"colorbar style={ylabel={%s}, font=\small}" % tex_escape(axes["value_label"])]
    body.append(r"\addplot[draw=none, mark=none, forget plot] coordinates {(-0.5,-0.5) (%s,%s)};"
                % (_c(len(cols) - 0.5), _c(len(rows_) - 0.5)))
    for index, r in enumerate(fig["data_rows"]):
        x, y = cols.index(r["variant"]), rows_.index(r["model"])
        color = heat_color(r["gain_pp"], v_max)
        name = "saHeat%d" % index
        colors.append((name, color))
        body.append(r"\fill[%s] (axis cs:%s,%s) rectangle (axis cs:%s,%s);" % (
            name, _c(x - 0.5), _c(y - 0.5), _c(x + 0.5), _c(y + 0.5)))
        text = tex_number(_gain_text(r["gain_pp"]))
        if r["ci_excludes_zero"]:
            text = r"\textbf{%s}" % text
        if r["ci_degenerate"]:
            text += tex_mark(DAGGER)
        body.append(r"\node[font=\scriptsize, text=%s] at (axis cs:%d,%d) {%s};" % (text_on(color), x, y, text))
    return _pgf_document(fig, colors, options, body)


def _pgf_stacked(fig):
    axes = fig["axes"]
    cats = axes["categories"]
    colors = [("saState%s" % chr(65 + i), c) for i, c in enumerate(axes["colors"])]
    options = ["width=10.5cm", "height=7cm", "ybar stacked", "bar width=10pt", "ymin=%s" % _c(axes["y_min"]),
               "ymax=%s" % _c(axes["y_max"]), "xtick=" + _ticks(len(cats)), "xticklabels=" + _labels(cats),
               r"x tick label style={rotate=45,anchor=east,font=\small}", "enlarge x limits=0.06",
               "xlabel={%s}" % tex_escape(axes["x_label"]), "ylabel={%s}" % tex_escape(axes["y_label"]),
               "legend cell align=left", _LEGEND]
    body = []
    for i, state in enumerate(axes["states"]):
        coords = []
        for x, tool in enumerate(cats):
            row = [r for r in fig["data_rows"] if r["tool"] == tool and r["state"] == state][0]
            coords.append("(%d,%s)" % (x, _c(row["share_pct"] or 0.0)))
        body.append(r"\addplot[fill=%s, draw=white, area legend] coordinates {%s};" % (colors[i][0], " ".join(coords)))
        body.append(r"\addlegendentry{%s}" % tex_escape(state))
    return _pgf_document(fig, colors, options, body)


def _pgf_scatter(fig):
    axes = fig["axes"]
    colors = [("saSeries%s" % chr(65 + i), c) for i, c in enumerate(axes["colors"])]
    pgf_marks = {"circle": "*", "square": "square*", "triangle": "triangle*"}
    options = ["width=11cm", "height=7cm", "xmin=%s" % _c(axes["x_min"]), "xmax=%s" % _c(axes["x_max"]),
               "ymin=%s" % _c(axes["y_min"]), "ymax=%s" % _c(axes["y_max"]),
               "xlabel={%s}" % tex_escape(axes["x_label"]), "ylabel={%s}" % tex_escape(axes["y_label"]),
               "grid=major", "legend cell align=left", _LEGEND]
    if axes["x_log"]:
        options += ["xmode=log", "log basis x=10", "log ticks with fixed point"]
    body = [r"\addplot[draw=black!40, forget plot] coordinates {(%s,0) (%s,0)};" % (_c(axes["x_min"]),
                                                                                   _c(axes["x_max"]))]
    for i, variant in enumerate(axes["series"]):
        pts = [r for r in fig["data_rows"] if r["variant"] == variant and r["gain_pp"] is not None]
        coords = " ".join("(%s,%s) [%d]" % (_c(r["output_tokens_millions"]), _c(r["gain_pp"]), r["label"])
                          for r in pts)
        body.append(r"\addplot[only marks, mark=%s, color=%s, mark size=2.5pt, nodes near coords, "
                    r"point meta=explicit symbolic, every node near coord/.append style={font=\tiny, text=black, "
                    r"anchor=south west, inner sep=1pt}] coordinates {%s};"
                    % (pgf_marks[axes["marks"][i]], colors[i][0], coords))
        body.append(r"\addlegendentry{%s}" % tex_escape(variant))
    return _pgf_document(fig, colors, options, body)


def figure_pgfplots(fig):
    render = {"grouped_bar": _pgf_grouped_bar, "line": _pgf_line, "heatmap": _pgf_heatmap,
              "stacked_bar": _pgf_stacked, "scatter": _pgf_scatter}.get(fig["kind"])
    if render is None:
        refuse("unknown figure kind %r" % fig["kind"])
    return render(fig)


# -- SVG -----------------------------------------------------------------------------------------------------

def _f(value):
    text = "%.2f" % float(value)
    return "0.00" if text == "-0.00" else text


class Svg:
    """Minimal deterministic SVG writer (elements in call order)."""

    def __init__(self, title, width=WIDTH, height=HEIGHT):
        self.title, self.width, self.height, self.items = title, width, height, []

    def rect(self, x, y, w, h, fill, tip=None, stroke=None):
        attrs = 'x="%s" y="%s" width="%s" height="%s" fill="%s"' % (_f(x), _f(y), _f(max(w, 0.0)), _f(max(h, 0.0)),
                                                                    fill)
        if stroke:
            attrs += ' stroke="%s" stroke-width="1"' % stroke
        self._mark("rect", attrs, tip)

    def line(self, x1, y1, x2, y2, stroke, width=1.0, dash=None):
        attrs = 'x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s"' % (
            _f(x1), _f(y1), _f(x2), _f(y2), stroke, _f(width))
        if dash:
            attrs += ' stroke-dasharray="%s"' % dash
        self.items.append("<line %s/>" % attrs)

    def polyline(self, points, stroke, width=2.0, dash=None):
        attrs = 'points="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"' % (
            " ".join("%s,%s" % (_f(x), _f(y)) for x, y in points), stroke, _f(width))
        if dash:
            attrs += ' stroke-dasharray="%s"' % dash
        self.items.append("<polyline %s/>" % attrs)

    def text(self, x, y, text, size=12, anchor="start", fill=TEXT, weight=None, rotate=None):
        attrs = 'x="%s" y="%s" font-size="%d" text-anchor="%s" fill="%s"' % (_f(x), _f(y), size, anchor, fill)
        if weight:
            attrs += ' font-weight="%s"' % weight
        if rotate is not None:
            attrs += ' transform="rotate(%s %s %s)"' % (_f(rotate), _f(x), _f(y))
        self.items.append("<text %s>%s</text>" % (attrs, xml_escape(str(text))))

    def marker(self, shape, x, y, fill, tip=None, size=5.0):
        if shape == "square":
            self._mark("rect", 'x="%s" y="%s" width="%s" height="%s" fill="%s" stroke="%s" stroke-width="1"' % (
                _f(x - size), _f(y - size), _f(2 * size), _f(2 * size), fill, SURFACE), tip)
        elif shape == "triangle":
            pts = ((x, y - size * 1.2), (x + size * 1.1, y + size * 0.9), (x - size * 1.1, y + size * 0.9))
            self._mark("polygon", 'points="%s" fill="%s" stroke="%s" stroke-width="1"' % (
                " ".join("%s,%s" % (_f(a), _f(b)) for a, b in pts), fill, SURFACE), tip)
        else:
            self._mark("circle", 'cx="%s" cy="%s" r="%s" fill="%s" stroke="%s" stroke-width="1"' % (
                _f(x), _f(y), _f(size), fill, SURFACE), tip)

    def _mark(self, tag, attrs, tip):
        if tip:
            self.items.append("<%s %s><title>%s</title></%s>" % (tag, attrs, xml_escape(tip), tag))
        else:
            self.items.append("<%s %s/>" % (tag, attrs))

    def caption(self, fig, top):
        """The figure caption below the plot, wrapped (never truncated); the
        picture grows to hold it."""
        y = top + 16
        for paragraph in caption_paragraphs(fig):
            for line in textwrap.wrap(paragraph, WRAP, break_long_words=True, break_on_hyphens=False) or [""]:
                self.text(20, y, line, size=10, fill=TEXT2)
                y += 13
            y += 3
        self.height = int(math.ceil(y + 6))

    def render(self):
        head = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
                'font-family="%s" role="img">' % (self.width, self.height, self.width, self.height, FONT))
        body = ["<title>%s</title>" % xml_escape(self.title),
                '<rect x="0" y="0" width="%d" height="%d" fill="%s"/>' % (self.width, self.height, SURFACE)]
        return ("\n".join([head] + body + self.items + ["</svg>"]) + "\n").encode("utf-8")


def _y_axis(svg, box, lo, hi, label, ticks=None):
    x0, y0, x1, y1 = box
    if ticks is None:
        ticks, step = nice_ticks(lo, hi)
    else:
        step = ticks[1] - ticks[0] if len(ticks) > 1 else 1.0
    lo, hi = ticks[0], ticks[-1]
    digits = _decimals(step)

    def scale(v):
        return y1 - (float(v) - lo) / (hi - lo) * (y1 - y0)

    for t in ticks:
        y = scale(t)
        svg.line(x0, y, x1, y, AXIS if abs(t) < 1e-9 else GRID, 1.0)
        svg.text(x0 - 8, y + 4, _minus(_c0("%.*f" % (digits, t))), size=11, anchor="end", fill=TEXT2)
    svg.line(x0, y0, x0, y1, AXIS, 1.0)
    svg.text(x0 - 48, (y0 + y1) / 2.0, label, size=12, anchor="middle", fill=TEXT2, rotate=-90)
    return scale


def _legend(svg, x, y, entries):
    """entries: (label, color, shape) with shape in rect / line / dashed / marker shapes."""
    for i, (label, color, shape) in enumerate(entries):
        yy = y + i * 20
        if shape == "rect":
            svg.rect(x, yy - 9, 12, 12, color)
        elif shape in ("line", "dashed"):
            svg.line(x - 2, yy - 3, x + 16, yy - 3, color, 2.0, "6 4" if shape == "dashed" else None)
        else:
            svg.marker(shape, x + 6, yy - 3, color, size=4.5)
        svg.text(x + 22, yy + 1, label, size=12, fill=TEXT)


def _frame(fig, svg):
    svg.text(20, 28, fig["title"], size=15, weight="600")


def _ci_tip(row, low="ci_low_pct", high="ci_high_pct"):
    if row.get(low) is None or row.get(high) is None:
        return ""
    return ", 95%% CI [%.1f, %.1f]%s" % (row[low], row[high], DAGGER if row.get("ci_degenerate") else "")


def _whisker_svg(svg, cx, scale, low, high, color=TEXT):
    svg.line(cx, scale(low), cx, scale(high), color, 1.2)
    for v in (low, high):
        svg.line(cx - 3, scale(v), cx + 3, scale(v), color, 1.2)


def _svg_grouped_bar(fig):
    axes = fig["axes"]
    svg = Svg(fig["title"])
    _frame(fig, svg)
    box = (80, 50, 560, 370)
    scale = _y_axis(svg, box, axes["y_min"], axes["y_max"], axes["y_label"])
    groups, series = axes["groups"], axes["series"]
    marks = axes.get("group_marks") or {}
    width = (box[2] - box[0]) / float(len(groups))
    bar = width * 0.72 / len(series)
    for g, group in enumerate(groups):
        left = box[0] + g * width + width * 0.14
        for i, name in enumerate(series):
            row = [r for r in fig["data_rows"] if r["block"] == group and r["series"] == name][0]
            x = left + i * bar
            if row["value_pct"] is None:
                svg.text(x + bar / 2.0, box[3] - 4, "n/a", size=10, anchor="middle", fill=TEXT2)
                continue
            top = scale(row["value_pct"])
            tip = "%s, %s: %.1f%% (%s/%s)%s" % (group, axes["legend"][i], row["value_pct"], row["numerator"],
                                                row["denominator"], _ci_tip(row))
            svg.rect(x + 1, top, bar - 2, scale(axes["y_min"]) - top, axes["colors"][i], tip)
            if _has_ci(row):
                _whisker_svg(svg, x + bar / 2.0, scale, row["ci_low_pct"], row["ci_high_pct"])
            if _is_degenerate(row):                 # the visible mark of a zero-width interval
                svg.text(x + bar / 2.0, top - 5, DAGGER, size=11, anchor="middle", fill=TEXT)
        label = group + (" [%s]" % marks[group] if group in marks else "")
        svg.text(box[0] + (g + 0.5) * width, box[3] + 20, label, size=12, anchor="middle")
    svg.line(box[0], box[3], box[2], box[3], AXIS, 1.0)
    svg.text((box[0] + box[2]) / 2.0, box[3] + 44, axes["x_label"], size=12, anchor="middle", fill=TEXT2)
    _legend(svg, 585, 70, [(s, c, "rect") for s, c in zip(axes["legend"], axes["colors"])])
    svg.caption(fig, box[3] + 54)
    return svg.render()


def _svg_line(fig):
    axes = fig["axes"]
    svg = Svg(fig["title"])
    _frame(fig, svg)
    box = (80, 50, 540, 370)
    scale = _y_axis(svg, box, axes["y_min"], axes["y_max"], axes["y_label"])
    xs = axes["x_values"]

    def sx(x):
        return box[0] + 30 + (x - xs[0]) / float(max(xs[-1] - xs[0], 1)) * (box[2] - box[0] - 60)

    for x in xs:
        svg.text(sx(x), box[3] + 20, str(x), size=12, anchor="middle")
    svg.line(box[0], box[3], box[2], box[3], AXIS, 1.0)
    svg.text((box[0] + box[2]) / 2.0, box[3] + 44, axes["x_label"], size=12, anchor="middle", fill=TEXT2)
    if axes.get("truncated"):
        svg.text(box[0] + 4, box[3] - 6, "axis truncated", size=10, fill=TEXT2)
    entries = []
    for s in axes["series"]:
        pts = [r for r in fig["data_rows"] if r["endpoint"] == s["endpoint"] and r["variant"] == s["variant"]
               and r["value_pct"] is not None]
        svg.polyline([(sx(r["step"] + s["dodge"]), scale(r["value_pct"])) for r in pts], s["color"], 2.0,
                     "6 4" if s["dashed"] else None)
        for r in pts:
            cx = sx(r["step"] + s["dodge"])
            if _has_ci(r):
                _whisker_svg(svg, cx, scale, r["ci_low_pct"], r["ci_high_pct"], s["color"])
            svg.marker(s["mark"], cx, scale(r["value_pct"]), s["color"],
                       "%s step %s: %.1f%% (%s/%s)%s" % (s["label"], r["step"], r["value_pct"], r["numerator"],
                                                         r["denominator"], _ci_tip(r)), size=4.0)
            if _is_degenerate(r):                   # the visible mark of a zero-width interval
                svg.text(cx, scale(r["value_pct"]) - 7, DAGGER, size=11, anchor="middle", fill=TEXT)
        entries.append((s["label"], s["color"], "dashed" if s["dashed"] else "line"))
    _legend(svg, 565, 70, entries)
    svg.caption(fig, box[3] + 54)
    return svg.render()


def _svg_heatmap(fig):
    axes = fig["axes"]
    cols, rows_ = axes["columns"], axes["rows"]
    cell_h = 26.0
    svg = Svg(fig["title"])
    svg.text(20, 28, fig["title"], size=15, weight="600")
    x0, y0 = 190.0, 70.0
    cell_w = min(130.0, 420.0 / len(cols))
    for j, v in enumerate(cols):
        svg.text(x0 + (j + 0.5) * cell_w, y0 - 10, v, size=12, anchor="middle")
    for i, m in enumerate(rows_):
        svg.text(x0 - 10, y0 + (i + 0.5) * cell_h + 4, m, size=12, anchor="end")
    for r in fig["data_rows"]:
        i, j = rows_.index(r["model"]), cols.index(r["variant"])
        color = heat_color(r["gain_pp"], axes["v_max"])
        tip = "%s, %s: %s pp (%s/%s)%s" % (r["model"], r["variant"], _gain_text(r["gain_pp"]), r["numerator"],
                                            r["denominator"], _ci_tip(r, "ci_low_pp", "ci_high_pp"))
        svg.rect(x0 + j * cell_w + 1, y0 + i * cell_h + 1, cell_w - 2, cell_h - 2, color, tip)
        svg.text(x0 + (j + 0.5) * cell_w, y0 + (i + 0.5) * cell_h + 4,
                 _minus(_gain_text(r["gain_pp"])) + (DAGGER if r["ci_degenerate"] else ""), size=11,
                 anchor="middle", fill=SURFACE if text_on(color) == "white" else TEXT,
                 weight="700" if r["ci_excludes_zero"] else None)
    legend_y = y0 + len(rows_) * cell_h + 30
    v_max = axes["v_max"]
    steps = 9
    for k in range(steps):
        value = -v_max + 2.0 * v_max * k / (steps - 1)
        svg.rect(x0 + k * 24, legend_y, 24, 12, heat_color(value, v_max))
    svg.text(x0, legend_y + 28, _minus("%+.1f" % -v_max), size=11, anchor="start", fill=TEXT2)
    svg.text(x0 + steps * 12, legend_y + 28, "0", size=11, anchor="middle", fill=TEXT2)
    svg.text(x0 + steps * 24, legend_y + 28, "%+.1f" % v_max, size=11, anchor="end", fill=TEXT2)
    svg.text(x0 + steps * 24 + 16, legend_y + 10, axes["value_label"], size=12, fill=TEXT2)
    svg.caption(fig, legend_y + 36)
    return svg.render()


def _svg_stacked(fig):
    axes = fig["axes"]
    svg = Svg(fig["title"])
    _frame(fig, svg)
    box = (80, 50, 560, 350)
    scale = _y_axis(svg, box, axes["y_min"], axes["y_max"], axes["y_label"])
    cats = axes["categories"]
    width = (box[2] - box[0]) / float(len(cats))
    for x, tool in enumerate(cats):
        bottom = 0.0
        left = box[0] + x * width + width * 0.18
        for state, color in zip(axes["states"], axes["colors"]):
            row = [r for r in fig["data_rows"] if r["tool"] == tool and r["state"] == state][0]
            share = row["share_pct"] or 0.0
            if share > 0:
                top = bottom + share
                svg.rect(left, scale(top), width * 0.64, scale(bottom) - scale(top), color,
                         "%s %s: %.1f%% (%s/%s)" % (tool, state, share, row["numerator"], row["denominator"]),
                         stroke=SURFACE)
                bottom = top
        svg.text(box[0] + (x + 0.5) * width, box[3] + 14, tool, size=11, anchor="end", rotate=-40)
    svg.line(box[0], box[3], box[2], box[3], AXIS, 1.0)
    _legend(svg, 585, 70, [(s, c, "rect") for s, c in zip(axes["states"], axes["colors"])])
    svg.caption(fig, box[3] + 80)
    return svg.render()


def _svg_scatter(fig):
    axes = fig["axes"]
    svg = Svg(fig["title"])
    _frame(fig, svg)
    box = (80, 50, 560, 370)
    scale_y = _y_axis(svg, box, axes["y_min"], axes["y_max"], axes["y_label"])
    if axes["x_log"]:
        (x_lo, x_hi), x_ticks = log_ticks(axes["x_min"], axes["x_max"])

        def sx(v):
            return box[0] + (math.log10(float(v)) - math.log10(x_lo)) / (
                math.log10(x_hi) - math.log10(x_lo)) * (box[2] - box[0])

        def tick_text(t):
            return ("%.6f" % t).rstrip("0").rstrip(".")
    else:
        x_ticks, x_step = nice_ticks(axes["x_min"], axes["x_max"])
        x_lo, x_hi = x_ticks[0], x_ticks[-1]

        def sx(v):
            return box[0] + (float(v) - x_lo) / (x_hi - x_lo) * (box[2] - box[0])

        def tick_text(t):
            return "%.*f" % (_decimals(x_step), t)
    for t in x_ticks:
        svg.line(sx(t), box[1], sx(t), box[3], GRID, 1.0)
        svg.text(sx(t), box[3] + 18, tick_text(t), size=10, anchor="middle", fill=TEXT2)
    svg.line(box[0], box[3], box[2], box[3], AXIS, 1.0)
    svg.text((box[0] + box[2]) / 2.0, box[3] + 42, axes["x_label"], size=12, anchor="middle", fill=TEXT2)
    for variant, color, shape in zip(axes["series"], axes["colors"], axes["marks"]):
        for r in fig["data_rows"]:
            if r["variant"] != variant or r["gain_pp"] is None:
                continue
            x, y = sx(r["output_tokens_millions"]), scale_y(r["gain_pp"])
            svg.marker(shape, x, y, color,
                       "%s, %s: %s pp (%s/%s), %s output tokens" % (
                           r["model"], variant, _gain_text(r["gain_pp"]), r["gain_numerator"], r["denominator"],
                           format(int(r["output_tokens"]), ",")))
            svg.text(x + 6, y - 5, str(r["label"]), size=10, fill=TEXT)
    _legend(svg, 585, 70, list(zip(axes["series"], axes["colors"], axes["marks"])))
    svg.caption(fig, box[3] + 52)
    return svg.render()


def figure_svg(fig):
    render = {"grouped_bar": _svg_grouped_bar, "line": _svg_line, "heatmap": _svg_heatmap,
              "stacked_bar": _svg_stacked, "scatter": _svg_scatter}.get(fig["kind"])
    if render is None:
        refuse("unknown figure kind %r" % fig["kind"])
    return render(fig)
